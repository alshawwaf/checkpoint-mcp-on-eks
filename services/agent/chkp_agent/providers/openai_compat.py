"""OpenAI-compatible providers: OpenAI, Azure OpenAI, and any server that speaks
the Chat Completions API (vLLM, Ollama, LiteLLM, ...).

Prompt caching on these providers is automatic for prefixes >= 1,024 tokens;
the agent keeps the system prompt and tool list first and stable so they cache,
sets `prompt_cache_key` on OpenAI, and reports `cached_tokens` as cache reads.
"""

from __future__ import annotations

import json

from .base import ProviderError, ToolCall, Turn, name_map


def to_openai_tools(rows):
    return [{"type": "function", "function": {"name": safe, "description": desc, "parameters": schema}}
            for safe, _mcp, desc, schema in rows]


def normalise_usage(usage):
    if not usage:
        return {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
    details = getattr(usage, "prompt_tokens_details", None)
    cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
    written = (getattr(details, "cache_write_tokens", 0) or 0) if details else 0
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    return {"in": max(prompt - cached, 0), "out": getattr(usage, "completion_tokens", 0) or 0,
            "cache_read": cached, "cache_write": written}


def accumulate_stream(chunks, on_text=None):
    """Fold Chat Completions stream chunks into (text, tool_calls, finish, usage). Pure."""
    text, calls, finish, usage = [], {}, None, None
    for chunk in chunks:
        if getattr(chunk, "usage", None):
            usage = chunk.usage
        for choice in chunk.choices or []:
            delta = choice.delta
            if getattr(delta, "content", None):
                text.append(delta.content)
                if on_text:
                    on_text(delta.content)
            for tc in getattr(delta, "tool_calls", None) or []:
                slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    slot["name"] += fn.name or ""
                    slot["args"] += fn.arguments or ""
            if choice.finish_reason:
                finish = choice.finish_reason
    return "".join(text), [calls[i] for i in sorted(calls)], finish, usage


class OpenAIFactory:
    def __init__(self, name, client, model, max_tokens=2048, cache_key="chkp-mcp-agent"):
        if not model:
            raise ValueError("LLM_MODEL is required for OpenAI-compatible providers "
                             "(the deployment name on Azure OpenAI)")
        self.name, self.client, self.model, self.max_tokens, self.cache_key = (
            name, client, model, max_tokens, cache_key)

    @classmethod
    def openai(cls, settings):
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key or None, base_url=settings.openai_base_url or None)
        cache = None if settings.openai_base_url else "chkp-mcp-agent"
        return cls("openai", client, settings.model, settings.max_tokens, cache)

    @classmethod
    def azure(cls, settings):
        from openai import AzureOpenAI

        client = AzureOpenAI(azure_endpoint=settings.azure_endpoint, api_key=settings.azure_api_key,
                             api_version=settings.azure_api_version)
        return cls("azure", client, settings.model, settings.max_tokens, None)

    def pick_model(self):
        return self.model, None

    def new(self, model=None):
        return OpenAIConversation(self, model or self.model)


class OpenAIConversation:
    caching = True

    def __init__(self, factory, model):
        self.f, self.model, self.note = factory, model, None
        self.provider = factory.name
        self.label = {"azure": "Azure OpenAI", "openai": "OpenAI"}.get(factory.name, "OpenAI-compatible")
        self.messages, self.tools, self.map = [], [], {}

    def start(self, system_prompt, specs):
        rows, self.map = name_map(specs)
        self.tools = to_openai_tools(rows)
        self.messages = [{"role": "system", "content": system_prompt}]

    def add_user(self, text):
        self.messages.append({"role": "user", "content": text})

    def step(self, on_text=None):
        kwargs = dict(model=self.model, messages=self.messages, stream=True,
                      stream_options={"include_usage": True}, max_completion_tokens=self.f.max_tokens)
        if self.tools:
            kwargs["tools"] = self.tools
        if self.f.cache_key:
            kwargs["prompt_cache_key"] = self.f.cache_key
        try:
            text, calls, finish, usage = accumulate_stream(self.f.client.chat.completions.create(**kwargs),
                                                           on_text)
        except Exception as e:  # noqa: BLE001 -- surface a clean message
            raise ProviderError(f"{self.label} call failed: {type(e).__name__}: {str(e)[:200]}") from None
        msg = {"role": "assistant", "content": text or None}
        if calls:
            msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                  "function": {"name": c["name"], "arguments": c["args"] or "{}"}} for c in calls]
        self.messages.append(msg)
        tool_calls = []
        for c in calls:
            try:
                args = json.loads(c["args"]) if c["args"].strip() else {}
            except ValueError:
                args = {}
            tool_calls.append(ToolCall(c["id"], self.map.get(c["name"], c["name"]), args))
        return Turn(text=text, tool_calls=tool_calls, usage=normalise_usage(usage),
                    stop="tool_use" if tool_calls else (finish or "stop"))

    def add_tool_results(self, results):
        for call, text, _is_error in results:
            self.messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
