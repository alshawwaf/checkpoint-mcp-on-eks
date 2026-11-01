"""Minimal MCP client for the Check Point gateway, on the official `mcp` SDK (>= 2.3).

    pip install "mcp>=2.3,<3" httpx2
    eval "$(python -m chkpmcpeks endpoints --format sh --reveal-secret)"   # or --format ps1 | iex
    python examples/mcp-clients/python_client.py https://www.checkpoint.com

Mints a Cognito client-credentials token, lists the aggregated catalog grouped by
server, then calls a reputation-service tool for the URL given. TLS is verified
(against CHKP_CA_FILE when the stack uses its self-signed demo certificate).
"""

from __future__ import annotations

import asyncio
import base64
import collections
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request

import httpx2
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client


def env(name):
    value = os.environ.get(name, "")
    if not value and name != "CHKP_CA_FILE":
        sys.exit(f"{name} is not set -- run: python -m chkpmcpeks endpoints --format sh --reveal-secret")
    return value


def ssl_context():
    ctx = ssl.create_default_context()
    if env("CHKP_CA_FILE"):
        ctx.load_verify_locations(env("CHKP_CA_FILE"))
    return ctx


def get_token():
    basic = base64.b64encode(f"{env('CHKP_CLIENT_ID')}:{env('CHKP_CLIENT_SECRET')}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": env("CHKP_SCOPE")}).encode()
    req = urllib.request.Request(env("CHKP_TOKEN_URL"), data=body, method="POST", headers={
        "Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)["access_token"]


async def main(target):
    headers = {"Authorization": f"Bearer {get_token()}"}
    async with httpx2.AsyncClient(headers=headers, verify=ssl_context(), timeout=httpx2.Timeout(30, read=300)) as http:
        async with streamable_http_client(env("CHKP_MCP_URL"), http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools, cursor = [], None
                while True:
                    page = await session.list_tools(
                        params=types.PaginatedRequestParams(cursor=cursor) if cursor else None)
                    tools += page.tools
                    cursor = page.next_cursor
                    if not cursor:
                        break
                by_server = collections.Counter(t.name.split("_", 1)[0] for t in tools)
                print(f"{len(tools)} tools through the gateway:")
                for server, n in sorted(by_server.items()):
                    print(f"  {server:20} {n}")

                rep = [t for t in tools if t.name.startswith("reputationservice_") and "url" in t.name.lower()]
                if not rep:
                    print("no reputation-service URL tool deployed")
                    return
                tool = rep[0]
                arg = next(iter((tool.input_schema or {}).get("properties", {"url": {}})))
                print(f"\ncalling {tool.name}({arg}={target!r})")
                result = await session.call_tool(tool.name, {arg: target})
                text = "\n".join(getattr(b, "text", "") for b in result.content)
                print(("ERROR: " if result.is_error else "") + text[:1500])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "https://www.checkpoint.com"))
