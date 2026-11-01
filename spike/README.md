# Gateway spike (Phase 1)

Before building the Helm chart around [agentgateway](https://agentgateway.dev), this spike ran the real
agentgateway binary (v1.7.0, checksum-verified from the official GitHub release) against two fake
`@chkp`-shaped MCP backends, using a config shaped exactly like the chart's.

```
python spike/run_spike.py      # 16 gateway checks
python spike/local_e2e.py      # agent on Amazon Bedrock -> agentgateway -> fake backends
```

Download the binary for your platform into `spike/bin/` first (it is gitignored), for example
`gh release download v1.7.0 -R agentgateway/agentgateway -p "agentgateway-windows-amd64.exe" -D spike/bin`.

## Results (2026-11-01)

| Check | Result |
|---|---|
| Config validates (`--validate-only`) | pass |
| Readiness endpoint `:15021/healthz/ready` | pass |
| No token gets HTTP 401 | pass |
| Tools are exposed as `<target>_<tool>` (`prefixMode: always`) | pass |
| Read-only CEL policy hides `add_host` from `tools/list` | pass |
| Calling a hidden mutating tool is denied | pass |
| `tools/call` routes to the right target | pass |
| Wrong scope, wrong client id, ID token, wrong issuer all see zero tools | pass |
| **Client headers such as `API-KEY`, `MANAGEMENT-HOST` never reach a backend** | pass, **only with the header allow-list** |
| One backend down: healthy targets are still served (`failureMode: failOpen`) | pass |
| A restarted backend recovers without client action (`statefulMode: stateless`) | pass |
| Prometheus metrics include MCP series (`:15020/metrics`) | pass |
| Local end-to-end on Amazon Nova 2 Lite with prompt caching (78–81% cache hits) | pass |

### The finding that changed the design

By default agentgateway **forwards client request headers to every MCP backend**. It strips only
`Authorization`. Several `@chkp` packages read credentials and settings from request headers
(`API-KEY`, `MANAGEMENT-HOST`, `WAF-ALLOW-WRITES`, and 32 others; see `CHKP_CREDENTIAL_HEADERS` in
`chkpmcpeks/config.py`). An authenticated client could therefore steer a server, or switch on
writes, with nothing but a header.

A deny-list of those names alone is not enough. It blocks the known names but lets any unknown
header through, as the spike showed with `X-Probe`. The chart therefore rebuilds the forwarded header
set from an **allow-list** of MCP protocol headers (`transformations.request.replace`), and layers the
credential-header deny-list underneath as defense in depth.
