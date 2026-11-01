"""MCP client side of the agent: list the gateway's tools and call them.

One MCP session per chat request. The gateway runs stateless toward its
backends, so there is nothing to keep warm and nothing to go stale.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp import types as mcp_types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client


@asynccontextmanager
async def gateway_session(url, token=""):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with create_mcp_http_client(headers=headers) as http:
        async with streamable_http_client(url, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def list_specs(session):
    """[(name, description, input_schema)] across every page."""
    specs, cursor = [], None
    while True:
        params = mcp_types.PaginatedRequestParams(cursor=cursor) if cursor else None
        res = await session.list_tools(params=params)
        for t in res.tools:
            specs.append((t.name, t.description or "", t.input_schema or {"type": "object", "properties": {}}))
        cursor = res.next_cursor
        if not cursor:
            return specs


def result_text(result):
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        parts.append(text if text is not None else str(block))
    return "\n".join(parts) if parts else "(no content)"


async def call(session, name, args):
    """Never raises: a failed tool becomes an error result the model can read."""
    try:
        res = await session.call_tool(name, args or {})
        return {"text": result_text(res), "error": bool(getattr(res, "is_error", False))}
    except Exception as e:  # noqa: BLE001
        return {"text": f"tool call failed: {e}", "error": True}
