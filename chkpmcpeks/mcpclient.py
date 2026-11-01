"""Client-side MCP calls through the public gateway endpoint (TLS verified,
trusting the stack's self-signed certificate when no domain is configured)."""

from __future__ import annotations

import asyncio
import collections

from .awsutil import log


def _client(token, ctx, extra_headers=None):
    import httpx2

    headers = {"Authorization": f"Bearer {token}", **(extra_headers or {})}
    return httpx2.AsyncClient(headers=headers, verify=ctx, timeout=httpx2.Timeout(30, read=300))


async def _with_session(url, token, ctx, fn, extra_headers=None):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with _client(token, ctx, extra_headers) as http:
        async with streamable_http_client(url, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)


async def _all_tools(session):
    from mcp import types

    names, cursor = [], None
    while True:
        res = await session.list_tools(params=types.PaginatedRequestParams(cursor=cursor) if cursor else None)
        names += [t.name for t in res.tools]
        cursor = res.next_cursor
        if not cursor:
            return names


def list_tools(url, token, ctx):
    return asyncio.run(_with_session(url, token, ctx, _all_tools))


def call_tool(url, token, ctx, name, args=None, extra_headers=None):
    async def _call(session):
        res = await session.call_tool(name, args or {})
        return bool(res.is_error), "\n".join(getattr(b, "text", str(b)) for b in res.content or [])
    return asyncio.run(_with_session(url, token, ctx, _call, extra_headers))


def summarize(names, separator="_"):
    """Per-server counts, logged and returned as lines."""
    by = collections.Counter(n.split(separator, 1)[0] for n in names if separator in n)
    lines = [f"  TOOLS THROUGH THE GATEWAY: {len(names)}"] + [f"    {k:20} {v}" for k, v in sorted(by.items())]
    for ln in lines:
        log(ln)
    return lines
