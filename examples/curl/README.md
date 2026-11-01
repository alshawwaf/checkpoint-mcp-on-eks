# Example: curl and scripts

Ready-to-run scripts for bash (macOS, Linux, Git Bash, WSL) and PowerShell. Each one gets a token, asks the agent, and calls the MCP gateway directly.

## bash

```bash
eval "$(python -m chkpmcpeks endpoints --format sh --reveal-secret)"
```

```bash
./examples/curl/ask-agent.sh "What is the reputation of https://www.checkpoint.com?"
```

```bash
./examples/curl/mcp-tools.sh
```

## PowerShell

```powershell
python -m chkpmcpeks endpoints --format ps1 --reveal-secret | Invoke-Expression
```

```powershell
./examples/curl/ask-agent.ps1 "What is the reputation of https://www.checkpoint.com?"
```

## What happens on the wire

1. `POST $CHKP_TOKEN_URL` with HTTP Basic `client_id:client_secret` and `grant_type=client_credentials&scope=chkp-mcp/invoke` returns an `access_token`.
2. `POST $CHKP_AGENT_URL` with `Authorization: Bearer <token>` and `{"prompt": "..."}` returns JSON: `result`, `model`, `usage`, `tool_calls`. Add `"stream": true` for server-sent events.
3. MCP over HTTP is JSON-RPC to `$CHKP_MCP_URL`: `initialize`, then `tools/list` and `tools/call`. The gateway is stateless toward the servers, so each request stands alone.
