# Example: MCP clients (Claude Code, Claude Desktop, VS Code, Cursor, your own code)

The gateway is a standard **streamable-HTTP MCP endpoint** at `$CHKP_MCP_URL`. It takes a bearer token in the `Authorization` header. Tools appear as `<server>_<tool>`, for example `reputationservice_…` or `documentation_…`.

```bash
eval "$(python -m chkpmcpeks endpoints --format sh)"
```

```bash
export CHKP_TOKEN="$(python -m chkpmcpeks token)"
```

Tokens last 60 minutes. Re-run the second command to refresh.

**Self-signed certificate (no domain):** Node-based clients trust an extra certificate through `NODE_EXTRA_CA_CERTS="$CHKP_CA_FILE"`. That covers Claude Code and `mcp-remote` for Claude Desktop. With a real `domain_name` you need nothing extra.

## Claude Code

```bash
NODE_EXTRA_CA_CERTS="$CHKP_CA_FILE" claude mcp add --transport http checkpoint "$CHKP_MCP_URL" --header "Authorization: Bearer $CHKP_TOKEN"
```

Then, in Claude Code: *"Use the checkpoint tools: what is the reputation of https://www.checkpoint.com?"*

## Claude Desktop

Claude Desktop reaches remote servers with header auth through [`mcp-remote`](https://www.npmjs.com/package/mcp-remote). Add this to `claude_desktop_config.json`. The file lives at `%APPDATA%\Claude\` on Windows and `~/Library/Application Support/Claude/` on macOS.

```json
{
  "mcpServers": {
    "checkpoint": {
      "command": "npx",
      "args": ["-y", "mcp-remote@latest", "https://<your-host>/mcp", "--header", "Authorization:${CHKP_AUTH}"],
      "env": {
        "CHKP_AUTH": "Bearer <paste: python -m chkpmcpeks token>",
        "NODE_EXTRA_CA_CERTS": "<path printed as CHKP_CA_FILE, only without a domain>"
      }
    }
  }
}
```

The same file is in [claude_desktop_config.json](claude_desktop_config.json).

## VS Code (GitHub Copilot agent mode) and Cursor

[.vscode/mcp.json](vscode-mcp.json) asks for the token once and keeps it in VS Code's secret storage:

```json
{
  "inputs": [{"type": "promptString", "id": "chkp-token", "description": "Check Point MCP bearer token", "password": true}],
  "servers": {
    "checkpoint": {
      "type": "http",
      "url": "https://<your-host>/mcp",
      "headers": {"Authorization": "Bearer ${input:chkp-token}"}
    }
  }
}
```

Cursor uses the same shape in `~/.cursor/mcp.json`, with `"url"` and `"headers"` under `mcpServers.checkpoint`.

## Your own code (Python, official `mcp` SDK)

[python_client.py](python_client.py) mints a token, lists the catalog grouped by server, and calls a reputation lookup. TLS is verified against the stack's certificate.

```bash
python examples/mcp-clients/python_client.py https://www.checkpoint.com
```

## Why clients cannot send Check Point credentials

Some `@chkp` servers can read credentials from request headers (`API-KEY`, `MANAGEMENT-HOST`, ...). Behind this gateway that is switched off by design: agentgateway forwards only MCP protocol headers, so every server uses its own secret. See [security](../../docs/security.md).
