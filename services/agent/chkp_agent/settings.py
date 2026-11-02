"""Agent configuration, read once from the environment (12-factor).

Every value has a safe default for local runs; the Helm chart sets them from
values.yaml and the ESO-synced secrets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name, default=""):
    return os.environ.get(name, default)


def _csv(name, default=""):
    return tuple(v.strip() for v in os.environ.get(name, default).split(",") if v.strip())


def _bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    return int(os.environ.get(name, str(default)))


@dataclass(frozen=True)
class Settings:
    # --- MCP gateway ---------------------------------------------------------
    gateway_url: str = field(default_factory=lambda: _env("GATEWAY_URL", "http://agentgateway:3000/mcp"))
    tool_separator: str = field(default_factory=lambda: _env("TOOL_SEPARATOR", "_"))
    # OAuth client-credentials the agent uses for ITS OWN calls to the gateway.
    token_url: str = field(default_factory=lambda: _env("GATEWAY_TOKEN_URL"))
    client_id: str = field(default_factory=lambda: _env("GATEWAY_CLIENT_ID"))
    client_secret: str = field(default_factory=lambda: _env("GATEWAY_CLIENT_SECRET"))
    token_scope: str = field(default_factory=lambda: _env("GATEWAY_TOKEN_SCOPE", "chkp-mcp/invoke"))

    # --- inbound auth (who may call /v1/chat) --------------------------------
    auth_disabled: bool = field(default_factory=lambda: _bool("AUTH_DISABLED"))
    auth_issuer: str = field(default_factory=lambda: _env("AUTH_ISSUER"))
    auth_jwks_url: str = field(default_factory=lambda: _env("AUTH_JWKS_URL"))
    auth_audience: str = field(default_factory=lambda: _env("AUTH_AUDIENCE"))
    auth_allowed_client_ids: tuple = field(default_factory=lambda: _csv("AUTH_ALLOWED_CLIENT_IDS"))
    auth_required_scope: str = field(default_factory=lambda: _env("AUTH_REQUIRED_SCOPE", "chkp-mcp/invoke"))

    # --- LLM -----------------------------------------------------------------
    provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "bedrock").lower())
    model: str = field(default_factory=lambda: _env("LLM_MODEL"))
    aws_region: str = field(default_factory=lambda: _env("AWS_REGION", _env("AWS_DEFAULT_REGION", "us-east-1")))
    openai_base_url: str = field(default_factory=lambda: _env("OPENAI_BASE_URL"))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    azure_endpoint: str = field(default_factory=lambda: _env("AZURE_OPENAI_ENDPOINT"))
    azure_api_key: str = field(default_factory=lambda: _env("AZURE_OPENAI_API_KEY"))
    azure_api_version: str = field(default_factory=lambda: _env("AZURE_OPENAI_API_VERSION", "2024-10-21"))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    anthropic_base_url: str = field(default_factory=lambda: _env("ANTHROPIC_BASE_URL"))
    anthropic_fallbacks: bool = field(default_factory=lambda: _bool("ANTHROPIC_FALLBACKS", True))
    llm_effort: str = field(default_factory=lambda: _env("LLM_EFFORT", "medium"))   # Anthropic API only
    max_turns: int = field(default_factory=lambda: _int("MAX_TURNS", 12))
    max_tokens: int = field(default_factory=lambda: _int("MAX_TOKENS", 2048))
    tool_result_chars: int = field(default_factory=lambda: _int("TOOL_RESULT_CHARS", 6000))

    # --- service -------------------------------------------------------------
    port: int = field(default_factory=lambda: _int("PORT", 8080))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))


def load():
    return Settings()
