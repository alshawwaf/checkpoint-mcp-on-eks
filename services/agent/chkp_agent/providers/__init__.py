"""LLM provider selection (LLM_PROVIDER = bedrock | anthropic | azure | openai)."""

from __future__ import annotations

from .base import ProviderError, ToolCall, Turn  # noqa: F401


def make_factory(settings):
    p = settings.provider
    if p == "bedrock":
        from .bedrock import BedrockFactory

        return BedrockFactory(settings.aws_region, settings.model, settings.max_tokens)
    if p in ("anthropic", "claude"):
        from .anthropic_api import AnthropicFactory

        return AnthropicFactory.from_settings(settings)
    if p in ("azure", "azure-openai", "azure_openai"):
        from .openai_compat import OpenAIFactory

        return OpenAIFactory.azure(settings)
    if p in ("openai", "openai-compatible", "openai_compatible"):
        from .openai_compat import OpenAIFactory

        return OpenAIFactory.openai(settings)
    raise ValueError(f"unknown LLM_PROVIDER '{p}' (expected bedrock, anthropic, azure or openai)")
