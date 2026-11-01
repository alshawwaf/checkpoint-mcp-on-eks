# Examples: one per consumer

Every consumer in the [architecture diagram](../docs/img/architecture.svg) has a working example here. All of them use the same two endpoints behind the ALB and the same Cognito client-credentials token.

| Consumer | Example | Talks to |
|---|---|---|
| `chkpmcpeks` CLI | [cli/](cli/README.md) | agent (`/v1/chat`) and gateway (`/mcp`) |
| Any MCP client: Claude Code, Claude Desktop, VS Code, Cursor, your own code | [mcp-clients/](mcp-clients/README.md) | gateway `/mcp` |
| curl and scripts (bash, PowerShell) | [curl/](curl/README.md) | agent and gateway |
| Postman | [postman/](postman/README.md) | agent and gateway; OAuth 2.0 handled by Postman |
| Microsoft Teams (Power Automate) | [teams/](teams/README.md) | agent |
| n8n: agentic workflows | [n8n/](n8n/README.md) | agent, and the gateway as MCP tools for n8n's own AI Agent |
| Argo CD / Flux (GitOps) | [gitops/](gitops/README.md) | the cluster, via the Helm chart |

## Values every example needs

```bash
python -m chkpmcpeks endpoints
```

It prints the values below. Add `--format sh` or `--format ps1` to get shell exports.

| Variable | Meaning |
|---|---|
| `CHKP_BASE_URL` | `https://<alb-or-your-domain>` |
| `CHKP_MCP_URL` | `$CHKP_BASE_URL/mcp`, the MCP gateway (streamable HTTP) |
| `CHKP_AGENT_URL` | `$CHKP_BASE_URL/v1/chat`, the agent API |
| `CHKP_TOKEN_URL` | the Cognito OAuth 2.0 token endpoint |
| `CHKP_CLIENT_ID` | the `external-clients` app client |
| `CHKP_SCOPE` | `chkp-mcp/invoke` |
| `CHKP_CA_FILE` | the stack's self-signed certificate to trust (empty with a real domain) |

The client secret is printed only with `--reveal-secret`. Put it in the tool's own credential store, never in a workflow body or a script you commit. A ready-made bearer token for quick tests:

```bash
python -m chkpmcpeks token
```

Tokens last 60 minutes. Every token request is billed by Cognito, so tools should cache them.

> **No domain yet?** The ALB serves a self-signed certificate. Each example shows how to trust it: `--cacert` for curl, `NODE_EXTRA_CA_CERTS` for Node-based MCP clients, an SSL context in Python, the certificate setting in Postman, and the *Ignore SSL issues* option in n8n. Set `domain_name` in Terraform for a publicly trusted certificate. The ALB hostname also changes on every fresh deploy, while a domain stays fixed.
