# Security notes

This stack exposes tools that can read, and with some servers change, a Check Point estate. Read this before you put real credentials in.

## Trust boundaries

```
internet ──TLS──► ALB ──► agentgateway ──► MCP server pods ──TLS──► Check Point APIs
                  │        (JWT + CEL)      (no inbound except      (management, ThreatCloud,
                  └──────► agent            from the gateway)        Infinity Portal)
                           (JWT) ──► Bedrock (Pod Identity)
```

| Control | Where | What it stops |
|---|---|---|
| Cognito client-credentials JWT, issuer + signature + expiry + `token_use` + client allow-list + scope | agentgateway (`mcpAuthentication` + CEL), agent (PyJWT) | Anonymous or foreign-issuer callers. A stolen ID token. Tokens from other app clients in the pool. |
| **Header allow-list** (rebuild headers from MCP protocol headers only) + credential-header deny-list | agentgateway `transformations` + `requestHeaderModifier` | A caller steering a server with `API-KEY`, `MANAGEMENT-HOST`, `S1C-URL`, `WAF-ALLOW-WRITES` and 31 other headers the `@chkp` packages read. Verified by `tests/test_gateway_chart_integration.py` and `tests/e2e/smoke.py`. |
| Read-only tool policy (`toolPolicy.readOnly`, on by default) | agentgateway CEL | Mutating tools (`add_*`, `set_*`, `delete_*`, `publish`, `install_*`, `quarantine`, ...) are hidden from `tools/list` and denied on call. Opt specific tools back in with `toolPolicy.allowTools`. |
| Default-deny NetworkPolicies | namespace `chkp-mcp` | Anything except the gateway reaching a server, servers reaching anything but `:443`, any pod reaching the instance metadata service. |
| EKS Pod Identity, one role per workload | ESO (read `chkp/*`), agent (`bedrock:InvokeModel*` only), CloudWatch agent | Node-wide credentials. MCP server pods have **no** AWS credentials at all. |
| Restricted Pod Security Standard | namespace label | Root containers, privilege escalation, host access. |
| Digest-pinned images, immutable tags, ECR scan on push, `npm install --ignore-scripts` | build | Tag mutation, install-hook supply-chain attacks. |

## Known upstream issues

- **On-prem management TLS verification is off in the `@chkp` client.** The `@chkp/quantum-infra` API client calls on-prem `MANAGEMENT_HOST` with `rejectUnauthorized: false`, so it accepts any certificate. Prefer Smart-1 Cloud (`S1C_URL`), whose client path verifies TLS. Otherwise patch the package (vendor and fix) or ask Check Point for a fix. `NODE_EXTRA_CA_CERTS` alone does not help while the flag is forced off.
- **Sessions live in process memory** in the `@chkp` HTTP transport, with no idle timeout. Servers run one replica with a memory limit, and the gateway's stateless mode opens short-lived sessions, so nothing accumulates. A leak ends in an OOM restart.
- **Interactive login** (`quantum-gaia` elicitation) cannot be relayed through the gateway. Desktop login dialogs (`mcp-utils` session context) cannot work in a container. Credentials must always be supplied up front.
- **Local files:** `threat-emulation` can look up hashes and URLs remotely, but it cannot upload a file from your laptop, because the pod cannot see your disk.

## Credentials

- Credentials live only in Secrets Manager (`chkp/<server>`) and in the per-pod Kubernetes Secret ESO syncs. EKS envelope-encrypts Kubernetes Secrets at rest.
- Use **read-only, least-privilege** Check Point API keys. The read-only gateway policy is defense in depth, not a replacement.
- Your local `chkp-credentials.env` is gitignored. Never commit it, and never paste values into issues or logs. The CLI prints key names only.

## Logging hygiene

- The agent logs prompt length, model, tool names, token counts and latency, never prompt text, tokens, headers or tool arguments.
- agentgateway's JSON access logs do not include request headers or tool arguments by default. Do not add `mcp.tool.arguments` to its access-log fields if arguments can contain secrets.
- ALB access logs are off. If you enable them, remember they contain query strings, though no tokens, since bearer tokens travel in headers.

## Exposure

- The ALB is internet-facing so demos work from anywhere. Restrict it with the Terraform variable `alb_inbound_cidrs`, or set `ingress.scheme: internal` for a private deployment.
- The EKS API endpoint is public with `0.0.0.0/0` by default for the same reason. Set `endpoint_public_access_cidrs` to your network.
- With no domain configured, the ALB uses a self-signed certificate. The CLI verifies it against the exported PEM, but desktop MCP clients will refuse it. Use `domain_name` for anything beyond a demo.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
