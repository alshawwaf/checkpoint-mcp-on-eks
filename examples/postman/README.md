# Example: Postman

1. **Import** [checkpoint-mcp-eks.postman_collection.json](checkpoint-mcp-eks.postman_collection.json).
2. Set the collection variables `baseUrl`, `tokenUrl`, `clientId` and `clientSecret` from the output of:

   ```bash
   python -m chkpmcpeks endpoints --reveal-secret
   ```

   Store `clientSecret` as a secret-type variable, or in a Postman Vault.
3. **Authorization tab** (collection level, OAuth 2.0 client credentials): click **Get New Access Token**, then **Use Token**. Postman sends it as `Authorization: Bearer …` on every request and fetches a new one when it expires.
4. **Self-signed demo certificate:** go to *Settings → Certificates → CA certificates* and add the file printed as `CHKP_CA_FILE`. Do not turn SSL verification off. A real `domain_name` removes this step.

| Request | What it shows |
|---|---|
| Agent / Ask the agent (JSON) | A grounded answer with `model`, `usage` and the `tool_calls` it made. The test asserts at least one tool call. |
| Agent / Ask the agent (streamed SSE) | The same answer as server-sent events: `start`, `tool_call`, `tool_result`, `text`, `done`. |
| MCP gateway / initialize, tools/list, tools/call | Raw MCP JSON-RPC over streamable HTTP, through the same gateway any MCP client uses. |
| MCP gateway / Negative | Without a token the gateway answers **401**. |

Run the whole collection with the Collection Runner, or in CI with `newman run checkpoint-mcp-eks.postman_collection.json --env-var baseUrl=... --env-var clientSecret=...`.
