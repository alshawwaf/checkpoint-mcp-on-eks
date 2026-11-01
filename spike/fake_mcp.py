"""A tiny @chkp-shaped MCP server for the agentgateway spike.

Serves streamable HTTP on /mcp (like `@chkp/*-mcp --transport http`) and records
the HTTP header NAMES of every request it receives, so the spike can prove the
gateway does not forward client-supplied headers (e.g. MANAGEMENT-HOST/API-KEY)
to the backend.

    python spike/fake_mcp.py <name> <port>
"""

import sys

import uvicorn
from mcp.server.mcpserver import MCPServer

NAME, PORT = sys.argv[1], int(sys.argv[2])
SEEN_HEADERS: set[str] = set()

server = MCPServer(NAME)


@server.tool()
def echo(text: str) -> str:
    """Echo the text back, tagged with this server's name."""
    return f"{NAME}: {text}"


@server.tool()
def show_hosts() -> str:
    """Read-only: list hosts."""
    return f"{NAME}: host-a, host-b"


@server.tool()
def add_host(name: str) -> str:
    """Mutating: add a host (must be hidden by the read-only policy)."""
    return f"{NAME}: added {name}"


@server.tool()
def seen_headers() -> str:
    """Return every request header NAME this backend has received."""
    return ",".join(sorted(SEEN_HEADERS))


inner = server.streamable_http_app(streamable_http_path="/mcp")


async def app(scope, receive, send):
    if scope["type"] == "http":
        for k, _ in scope.get("headers", []):
            SEEN_HEADERS.add(k.decode("latin-1").lower())
    await inner(scope, receive, send)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
