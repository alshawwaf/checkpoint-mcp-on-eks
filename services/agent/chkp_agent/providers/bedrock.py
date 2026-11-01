"""Amazon Bedrock Converse provider (model invocation only -- no AgentCore).

Ported from the AgentCore project's field-tested agent:
  * prompt caching: a cachePoint after the static system prompt (Claude and
    Nova) and after the tool block (Claude only -- Nova rejects it there);
  * streaming via ConverseStream, with a non-streaming fallback for models that
    deterministically fail to stream some tool calls (seen with Nova Lite);
  * bounded retries on transient/model-side errors;
  * model auto-selection: the first model this account can actually invoke,
    Claude preferred, Amazon Nova as the fallback. The probe result is cached
    for 15 minutes, so Claude is picked up automatically once Anthropic's
    use-case form is approved -- no redeploy.
Credentials come from EKS Pod Identity through boto3's default chain.
"""

from __future__ import annotations

import json
import threading
import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .base import ProviderError, ToolCall, Turn, name_map

MODEL_PREFERENCE = (
    "us.anthropic.claude-sonnet-5-5",
    "us.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-haiku-5-5",
    "us.amazon.nova-2-lite-v1:0",
    "us.amazon.nova-lite-v1:0",
    "us.amazon.nova-micro-v1:0",
)
PROBE_TTL = 900

TRANSIENT_CODES = {
    "ModelErrorException", "ModelTimeoutException", "ThrottlingException",
    "ServiceUnavailableException", "InternalServerException",
    "ModelStreamErrorException", "modelStreamErrorException",
}


def err_code(exc):
    try:
        return exc.response["Error"]["Code"]
    except Exception:
        return ""


def supports_system_caching(model):
    m = model.lower()
    return "claude" in m or "anthropic" in m or "nova" in m


def supports_tool_caching(model):
    m = model.lower()
    return "claude" in m or "anthropic" in m


def label(model):
    m = model.lower()
    if "claude" in m or "anthropic" in m:
        return "Claude on Amazon Bedrock"
    if "nova" in m:
        return "Amazon Nova on Bedrock"
    return "Amazon Bedrock"


def build_tool_config(rows, model):
    tools = [{"toolSpec": {"name": safe, "description": desc, "inputSchema": {"json": schema}}}
             for safe, _mcp, desc, schema in rows]
    if supports_tool_caching(model):
        tools.append({"cachePoint": {"type": "default"}})
    return {"tools": tools}


def reconstruct_stream(events, on_text=None):
    """Rebuild a Converse message from ConverseStream events (pure; tested).
    Returns (message, stop_reason, usage)."""
    blocks, stop_reason, usage = {}, None, {}
    for event in events:
        if "contentBlockStart" in event:
            ev = event["contentBlockStart"]
            start = ev.get("start", {})
            if "toolUse" in start:
                blocks[ev["contentBlockIndex"]] = {"kind": "tool", "tu": start["toolUse"], "input": ""}
        elif "contentBlockDelta" in event:
            ev = event["contentBlockDelta"]
            idx, delta = ev["contentBlockIndex"], ev["delta"]
            if "text" in delta:
                b = blocks.setdefault(idx, {"kind": "text", "text": ""})
                b["text"] += delta["text"]
                if on_text:
                    on_text(delta["text"])
            elif "toolUse" in delta and idx in blocks:
                blocks[idx]["input"] += delta["toolUse"].get("input", "")
        elif "messageStop" in event:
            stop_reason = event["messageStop"].get("stopReason")
        elif "metadata" in event:
            usage = event["metadata"].get("usage", {}) or {}
    content = []
    for idx in sorted(blocks):
        b = blocks[idx]
        if b["kind"] == "text":
            content.append({"text": b["text"]})
        else:
            try:
                args = json.loads(b["input"]) if b["input"].strip() else {}
            except ValueError:
                args = {}
            content.append({"toolUse": {"toolUseId": b["tu"]["toolUseId"], "name": b["tu"]["name"],
                                        "input": args}})
    return {"role": "assistant", "content": content}, stop_reason, usage


def normalise_usage(u):
    return {"in": u.get("inputTokens", 0) or 0, "out": u.get("outputTokens", 0) or 0,
            "cache_read": u.get("cacheReadInputTokens", 0) or 0,
            "cache_write": u.get("cacheWriteInputTokens", 0) or 0}


def _retry(fn, attempts=3, base_delay=1.5):
    last = None
    for attempt in range(attempts):
        try:
            return fn()
        except ClientError as e:
            last = e
            if err_code(e) in TRANSIENT_CODES and attempt < attempts - 1:
                time.sleep(base_delay * (attempt + 1))
                continue
            raise
    raise last  # pragma: no cover


def robust_converse(client, on_text=None, **kwargs):
    """Stream with retry; fall back to plain Converse on deterministic stream errors."""
    try:
        return _retry(lambda: reconstruct_stream(client.converse_stream(**kwargs)["stream"], on_text))
    except ClientError as e:
        if err_code(e).lower() != "modelstreamerrorexception":
            raise
        resp = _retry(lambda: client.converse(**kwargs))
        msg = resp["output"]["message"]
        text = "".join(b.get("text", "") for b in msg.get("content", []))
        if on_text and text.strip():
            on_text(text)
        return msg, resp.get("stopReason"), resp.get("usage", {}) or {}


def access_reason(exc):
    msg = str(exc).lower()
    return "use-case-form" if ("use case" in msg or "not been submitted" in msg) else "no-access"


class BedrockFactory:
    name = "bedrock"

    def __init__(self, region, model="", max_tokens=2048, client=None, preference=MODEL_PREFERENCE):
        self.region, self.forced, self.max_tokens = region, model, max_tokens
        self.client = client or boto3.client("bedrock-runtime", region_name=region)
        self.preference = preference
        self._pick, self._picked_at, self._lock = None, 0.0, threading.Lock()

    def _callable(self, model):
        try:
            self.client.converse(modelId=model, messages=[{"role": "user", "content": [{"text": "hi"}]}],
                                 inferenceConfig={"maxTokens": 4})
            return True, None
        except (ClientError, BotoCoreError) as e:
            return False, access_reason(e)

    def pick_model(self):
        """(model, note). Forced model wins; otherwise first callable preference."""
        if self.forced:
            return self.forced, None
        with self._lock:
            if self._pick and time.time() - self._picked_at < PROBE_TTL:
                return self._pick
            form_blocked = False
            pick = (self.preference[0], "none of the preferred models are callable")
            for i, model in enumerate(self.preference):
                ok, reason = self._callable(model)
                if ok:
                    note = None if i == 0 else (
                        "Claude is enabled but Anthropic's one-time use-case form is not submitted; "
                        "using " + model if form_blocked else "earlier preferences not enabled; using " + model)
                    pick = (model, note)
                    break
                if "anthropic" in model and reason == "use-case-form":
                    form_blocked = True
            self._pick, self._picked_at = pick, time.time()
            return pick

    def new(self, model=None):
        chosen, note = (model, None) if model else self.pick_model()
        return BedrockConversation(self.client, chosen, self.max_tokens, note)


class BedrockConversation:
    provider = "bedrock"

    def __init__(self, client, model, max_tokens, note=None):
        self.client, self.model, self.max_tokens, self.note = client, model, max_tokens, note
        self.label = label(model)
        self.caching = supports_system_caching(model)
        self.messages, self.system, self.tool_config, self.map = [], [], None, {}

    def start(self, system_prompt, specs):
        rows, self.map = name_map(specs)
        self.tool_config = build_tool_config(rows, self.model)
        self.system = [{"text": system_prompt}]
        if self.caching:
            self.system.append({"cachePoint": {"type": "default"}})

    def add_user(self, text):
        self.messages.append({"role": "user", "content": [{"text": text}]})

    def step(self, on_text=None):
        kwargs = dict(modelId=self.model, system=self.system, messages=self.messages,
                      inferenceConfig={"maxTokens": self.max_tokens})
        if self.tool_config and self.tool_config["tools"]:
            kwargs["toolConfig"] = self.tool_config
        try:
            msg, stop, usage = robust_converse(self.client, on_text, **kwargs)
        except ClientError as e:
            code = err_code(e)
            if code in ("AccessDeniedException",) or access_reason(e) == "use-case-form":
                raise ProviderError(f"Bedrock denied model {self.model} ({code}). Enable model access, "
                                    "or set LLM_MODEL to a model this account can invoke.") from None
            raise ProviderError(f"Bedrock call failed: {code or e}") from None
        self.messages.append(msg)
        calls = [ToolCall(b["toolUse"]["toolUseId"], self.map.get(b["toolUse"]["name"], b["toolUse"]["name"]),
                          b["toolUse"].get("input") or {})
                 for b in msg.get("content", []) if "toolUse" in b]
        text = "".join(b.get("text", "") for b in msg.get("content", []) if "text" in b)
        return Turn(text=text, tool_calls=calls, usage=normalise_usage(usage),
                    stop="tool_use" if stop == "tool_use" else (stop or "end_turn"))

    def add_tool_results(self, results):
        self.messages.append({"role": "user", "content": [
            {"toolResult": {"toolUseId": call.id, "content": [{"text": text}],
                            "status": "error" if is_error else "success"}}
            for call, text, is_error in results]})
