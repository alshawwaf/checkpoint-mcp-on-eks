# Example: Microsoft Teams (Power Automate)

Ask the Check Point agent from a Teams channel: someone posts `@flow reputation https://example.com`, or uses any keyword you choose, and the answer is posted back in the thread.

The agent is already an authenticated HTTPS service, so there is no bridge to build. Power Automate's **HTTP** action can fetch the OAuth token and call `/v1/chat` directly. The HTTP connector is a premium connector.

> Power Automate calls the agent from Microsoft's cloud, so the ALB must be reachable from the internet (the default) and serve a **publicly trusted certificate**. Power Automate cannot trust a self-signed certificate, so set `domain_name` in Terraform first.

## Store the client secret

Put the `external-clients` client secret in **Azure Key Vault** and read it with the *Get secret* action, or use a secure environment variable in a Power Platform solution. The secret comes from `python -m chkpmcpeks endpoints --reveal-secret`. Do not paste it into the flow definition.

## Build the flow

1. **Trigger:** *Microsoft Teams → When keywords are mentioned*. Pick your team and channel; keyword `reputation`. Or use *When a new channel message is added* and filter on a prefix.
2. **Get a token:** *HTTP* action.
   - Method `POST`, URI `<CHKP_TOKEN_URL>`.
   - Headers: `Content-Type: application/x-www-form-urlencoded`.
   - Authentication: **Basic**, with username = client id and password = the Key Vault secret.
   - Body: `grant_type=client_credentials&scope=chkp-mcp/invoke`.
3. **Parse JSON** on the token response with the schema `{"type":"object","properties":{"access_token":{"type":"string"}}}`.
4. **Ask the agent:** *HTTP* action.
   - Method `POST`, URI `https://<your-domain>/v1/chat`.
   - Headers: `Authorization: Bearer @{body('Parse_JSON')?['access_token']}` and `Content-Type: application/json`.
   - Body: `{"prompt": "@{triggerOutputs()?['body/body/plainTextContent']}"}`.
   - Settings: timeout `PT2M`. Answers usually take 3–15 seconds.
5. **Reply:** *Microsoft Teams → Reply with a message in a channel*.
   - Message: `@{body('HTTP_2')?['result']}`.
   - Add a footer with `model @{body('HTTP_2')?['model']} · tools @{length(body('HTTP_2')?['tool_calls'])}` so readers can see the answer came from live tools.

## Test it without Teams

The flow does exactly what the curl example does:

```bash
./examples/curl/ask-agent.sh "What is the reputation of https://example.com?"
```

If that works, the flow works, given a publicly trusted certificate.
