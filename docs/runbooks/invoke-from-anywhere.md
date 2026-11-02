# Runbook: call the gateway and the agent from other tools

Both endpoints sit behind the same ALB and accept a Cognito **client-credentials** bearer token. There is no bridge to provision, unlike the AgentCore project: the agent is already an authenticated HTTPS service.

## Get a token

The client secret lives in Cognito. Print it once and store it in your tool's secret store. Never paste it into chat or tickets.

```bash
python -m chkpmcpeks endpoints --reveal-secret
```

`--copy-secret` puts it on the clipboard instead of printing it. Then request a token:

```bash
curl -s -u "$CLIENT_ID:$CLIENT_SECRET" -d "grant_type=client_credentials&scope=chkp-mcp/invoke" "$TOKEN_URL"
```

Tokens last 60 minutes. Cache them: every token request is billed.

## Ask the agent (curl, n8n, Power Automate / Teams, webhooks)

Self-signed demo certificate: add `--cacert ~/.chkpmcpeks/<cluster>-alb-ca.pem`, or use a real domain.

```bash
curl -s "$BASE/v1/chat" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"prompt": "What is the reputation of https://example.com?"}'
```

The response looks like this:

```json
{"result": "...", "model": "us.amazon.nova-2-lite-v1:0", "usage": {"in": 290, "out": 40, "cache_read": 1200, "cache_write": 1311}, "tool_calls": [{"name": "reputationservice_...", "error": false}]}
```

Add `"stream": true` to get server-sent events (`start`, `tool_call`, `tool_result`, `text`, `done`). Add `"model": "..."` to force a model.

## Use the MCP gateway from an MCP client

The endpoint is `https://<host>/mcp` (streamable HTTP) with the header `Authorization: Bearer <token>`. Tools appear as `<server>_<tool>`.

```bash
claude mcp add --transport http checkpoint https://mcp.example.com/mcp --header "Authorization: Bearer $TOKEN"
```

Desktop clients require a publicly trusted certificate, so set `domain_name` in Terraform. The gateway also publishes OAuth protected-resource metadata at `/.well-known/oauth-protected-resource/mcp` for clients that discover the authorization server automatically.

Clients cannot pass Check Point credentials in headers: the gateway strips them by design. Credentials come from the server's own secret.
