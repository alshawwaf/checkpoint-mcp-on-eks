"""Provider interface: one conversation with one LLM, in that LLM's native
message format. The tool-use loop (chkp_agent.loop) is provider-agnostic.

    p = factory.new()
    p.start(system_prompt, specs)          # specs: [(mcp_name, description, schema)]
    p.add_user("question")
    turn = p.step(on_text)                 # Turn(text, tool_calls, usage, stop)
    p.add_tool_results([(call, text, is_error), ...])
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str          # the MCP (gateway) tool name
    args: dict


@dataclass
class Turn:
    text: str = ""
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)   # normalised: in/out/cache_read/cache_write
    stop: str = ""


def empty_usage():
    return {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}


def add_usage(total, part):
    for k in total:
        total[k] += int(part.get(k, 0) or 0)
    return total


def sanitize_tool_name(name, seen):
    """LLM tool names must match [a-zA-Z0-9_-]{1,64} and be unique per request.
    Gateway names are usually fine but can exceed 64 chars; sanitize + de-dup."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:64] or "tool"
    base, i = safe, 1
    while safe in seen:
        suffix = f"_{i}"
        safe = base[: 64 - len(suffix)] + suffix
        i += 1
    seen.add(safe)
    return safe


def clean_schema(schema):
    """Both Bedrock and OpenAI want an object schema; normalise the minimum."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return {"type": "object", "properties": {}}
    schema = dict(schema)
    schema.setdefault("properties", {})
    return schema


def name_map(specs):
    """[(llm_name, mcp_name, description, schema)] plus {llm_name: mcp_name}."""
    seen, rows, mapping = set(), [], {}
    for name, desc, schema in specs:
        safe = sanitize_tool_name(name, seen)
        mapping[safe] = name
        rows.append((safe, name, ((desc or name).strip() or name)[:1000], clean_schema(schema)))
    return rows, mapping


class ProviderError(Exception):
    """A provider failure with an operator-facing message (no secrets)."""
