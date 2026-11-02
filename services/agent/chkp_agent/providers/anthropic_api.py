"""Claude through the Anthropic API directly (an `ANTHROPIC_API_KEY`), with the
official `anthropic` SDK -- for teams that hold a Claude API key with its own
spend limit instead of (or before) Bedrock model access.

  * streaming Messages API; the full assistant content (thinking blocks
    included) goes back into the history unchanged, as the API requires;
  * prompt caching: an explicit breakpoint after the system prompt (which
    caches tools + system, the stable prefix) plus top-level automatic
    caching, which moves the second breakpoint along the growing transcript;
  * refusals: `stop_reason == "refusal"` ends the task cleanly and never runs
    tools from that turn; server-side fallbacks are on by default on the
    Claude API (`fallbacks: "default"`) and can be turned off for proxies;
  * a turn cut off by `max_tokens` while writing a tool call runs no tools.
"""

from __future__ import annotations

from .base import ProviderError, ToolCall, Turn, name_map

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MIN_MAX_TOKENS = 16000      # adaptive thinking counts toward max_tokens; you pay only for what is generated


def to_anthropic_tools(rows):
    return [{"name": safe, "description": desc, "input_schema": schema} for safe, _mcp, desc, schema in rows]


def normalise_usage(usage):
    if usage is None:
        return {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
    return {"in": getattr(usage, "input_tokens", 0) or 0,
            "out": getattr(usage, "output_tokens", 0) or 0,
            "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0}


def parse_message(msg, mapping):
    """Final Message -> (text, tool_calls, stop). Pure; tested."""
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    stop = msg.stop_reason or "end_turn"
    calls = []
    if stop == "tool_use":
        for b in msg.content:
            if getattr(b, "type", "") == "tool_use":
                args = b.input if isinstance(b.input, dict) else {}
                calls.append(ToolCall(b.id, mapping.get(b.name, b.name), args))
    return text, calls, stop


class AnthropicFactory:
    def __init__(self, client, model="", max_tokens=2048, effort="medium", fallbacks=True):
        self.client, self.model = client, model or DEFAULT_MODEL
        self.max_tokens = max(int(max_tokens or 0), MIN_MAX_TOKENS)
        self.effort, self.fallbacks = effort, fallbacks

    @classmethod
    def from_settings(cls, settings):
        import anthropic

        if not settings.anthropic_api_key:
            raise ValueError("LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY (from the stack's LLM secret)")
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key,
                                     base_url=settings.anthropic_base_url or None)
        # A custom base URL is usually a gateway/proxy that may not accept betas.
        fallbacks = settings.anthropic_fallbacks and not settings.anthropic_base_url
        return cls(client, settings.model, settings.max_tokens, settings.llm_effort, fallbacks)

    def pick_model(self):
        return self.model, None

    def new(self, model=None):
        return AnthropicConversation(self, model or self.model)


class AnthropicConversation:
    caching = True
    provider = "anthropic"
    label = "Claude (Anthropic API)"

    def __init__(self, factory, model):
        self.f, self.model, self.note = factory, model, None
        self.system, self.tools, self.map, self.messages = [], [], {}, []

    def start(self, system_prompt, specs):
        rows, self.map = name_map(specs)
        self.tools = to_anthropic_tools(rows)
        self.system = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]

    def add_user(self, text):
        self.messages.append({"role": "user", "content": text})

    def _request(self):
        kw = dict(model=self.model, max_tokens=self.f.max_tokens, system=self.system,
                  messages=self.messages, cache_control={"type": "ephemeral"})
        if self.tools:
            kw["tools"] = self.tools
        if self.f.effort:
            kw["output_config"] = {"effort": self.f.effort}
        if self.f.fallbacks:
            kw["betas"] = [FALLBACK_BETA]
            kw["fallbacks"] = "default"
        return kw

    def step(self, on_text=None):
        import anthropic

        try:
            with self.f.client.beta.messages.stream(**self._request()) as stream:
                for delta in stream.text_stream:
                    if on_text:
                        on_text(delta)
                msg = stream.get_final_message()
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic API error {e.status_code}: {str(e.message)[:200]}") from None
        except anthropic.APIConnectionError as e:
            raise ProviderError(f"Anthropic API unreachable: {type(e).__name__}") from None
        # Thinking/fallback blocks must go back unchanged -- append the whole content.
        self.messages.append({"role": "assistant", "content": msg.content})
        if msg.model and msg.model != self.model:
            self.note = f"served by fallback model {msg.model}"
        text, calls, stop = parse_message(msg, self.map)
        if stop == "refusal" and not text:
            text = "The model declined this request."
        return Turn(text=text, tool_calls=calls, usage=normalise_usage(msg.usage),
                    stop="tool_use" if calls else stop)

    def add_tool_results(self, results):
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call.id, "content": text, "is_error": bool(is_error)}
            for call, text, is_error in results]})
