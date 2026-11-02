# n8n: agentic workflows

Two importable workflows, built and run on n8n 2.28 against a live stack. Workflow 1 answers end to end. Workflow 2 fetches its gateway token as described below; its last test stopped at a wrong client secret in the n8n credential.

| Workflow | What it does | Uses |
|---|---|---|
| [ask-checkpoint-agent.workflow.json](ask-checkpoint-agent.workflow.json) | Chat, then a Cognito token, then `POST /v1/chat`. The EKS agent picks the Check Point tools and answers. | the agent |
| [n8n-ai-agent-with-checkpoint-mcp.workflow.json](n8n-ai-agent-with-checkpoint-mcp.workflow.json) | n8n's own AI Agent gets every Check Point tool from the gateway over MCP. Claude is the main model and OpenAI the fallback. | the gateway `/mcp` |

Import either one with **Workflows → Import from file**, or paste the JSON onto an empty canvas.

## Values you need

```bash
python -m chkpmcpeks endpoints --reveal-secret
```

Put the client secret only in an n8n credential. Never put it in a workflow field.

## 1 · Ask the Check Point agent

1. In the **Config** node, set `baseUrl` to `CHKP_BASE_URL` and `tokenUrl` to `CHKP_TOKEN_URL`.
2. Create a **Basic Auth** credential. The user is the client ID and the password is the client secret. Select it in **Get Cognito token**.
3. Open the chat and ask a question.

The **Answer** node appends the model, the tools the agent called and the cache hit rate to each reply.

## 2 · n8n AI Agent with Check Point MCP tools

1. Create an **MCP OAuth2** credential with these settings:

   | Field | Value |
   |---|---|
   | Use Dynamic Client Registration | off |
   | Grant Type | Client Credentials |
   | Access Token URL | `CHKP_TOKEN_URL` |
   | Client ID / Client Secret | from `endpoints --reveal-secret` |
   | Scope | `chkp-mcp/invoke` |
   | Authentication | Header |

2. Select that credential in both **Refresh gateway token** and **Check Point MCP gateway**. Set both URLs to `CHKP_MCP_URL`.
3. Select an Anthropic credential in **Claude (main)** and an OpenAI credential in **OpenAI (fallback)**. Any tool-calling chat model works in either slot.
4. Open the chat and ask: *What is the reputation of https://www.checkpoint.com?*

**Why the workflow starts with a token step.** The MCP Client Tool node needs node version 1.2 or later for OAuth2. In n8n 2.28 it sends the token stored on the credential, but it never fetches a client-credentials token itself. The HTTP Request node does fetch one, stores it on the same credential, and fetches a new one when the gateway answers 401. Running it first keeps the token the MCP node reads valid. Newer n8n releases refresh MCP OAuth2 tokens in the MCP node itself, so there you can remove the step.

**Choosing the model.** The gateway exposes over a hundred tools, and n8n sends every tool definition on each model call. Pick the Anthropic model in **Claude (main)** with your budget in mind. To send fewer tools, set **Tools to Include** on the MCP node to the servers you need.

## Certificates

The MCP Client Tool node has no option to skip certificate checks. It needs the stack deployed with a domain and a publicly trusted certificate:

```bash
python -m chkpmcpeks deploy --domain mcp.example.com
```

Workflow 1 can run against the self-signed demo certificate if you turn on **Ignore SSL Issues** in **Ask the Check Point agent**. Turn it off once a domain is set.

## Troubleshooting

| Symptom | Cause |
|---|---|
| *Failed to acquire OAuth2 access token: Client authentication failed* | The client ID or secret in the MCP OAuth2 credential is wrong. Paste the secret again with no spaces or line breaks. |
| *JWT token required* or *the token header is malformed* | The MCP node ran without a stored token. Check that **Refresh gateway token** runs first and uses the same credential. |
| The agent answers without calling a tool | The model did not pick a tool. Ask more specifically, or use a stronger model. |
