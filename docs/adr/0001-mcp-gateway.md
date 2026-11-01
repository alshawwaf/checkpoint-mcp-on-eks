# ADR 0001: agentgateway as the MCP gateway

**Status:** accepted, 2026-11-01

## Context

Fifteen `@chkp` MCP servers must appear to clients as **one** authenticated streamable-HTTP MCP endpoint, with each server's tools namespaced, JWT validation in front, health and readiness endpoints, and per-tool observability. On Bedrock AgentCore the AgentCore Gateway did this. On EKS we need something that runs in the cluster.

## Options considered

| Option | Verdict |
|---|---|
| **agentgateway** (Linux Foundation, Rust) in standalone mode | Multiplexes MCP targets, validates JWTs against a JWKS, CEL authorization per tool, OpenTelemetry and Prometheus metrics, readiness endpoint, multi-arch image. One Deployment + ConfigMap; no CRDs or control plane. Tool prefix is `<target>_<tool>` and not configurable. |
| Purpose-built Python gateway on the `mcp` SDK | Exact `___` naming parity with AgentCore, but we would own MCP spec drift, the SDK 2.0 API break and the auth path, in a security vendor's reference design. |
| IBM ContextForge | Needs PostgreSQL and Redis, still a release candidate, tool naming undocumented. |
| agentgateway Kubernetes mode (kgateway) | Gateway API CRDs plus a control plane; clashes with EKS Auto Mode's own Gateway API ownership. Too much for a two-node demo. |

## Decision

agentgateway v1.7.0 in standalone mode, rendered from the Helm chart, with `prefixMode: always`, `statefulMode: stateless`, and `failureMode: failOpen`. Tools are `<server-without-hyphens>_<tool>`, for example `reputationservice_…`. The agent reads `TOOL_SEPARATOR` (default `_`), so the same agent works against the AgentCore project's `___` names.

## Consequences

- **Header forwarding (security):** agentgateway forwards client request headers to backends by default, and `@chkp` servers read credentials from headers. The chart rebuilds the forwarded headers from an allow-list and strips 35 known credential headers. See [the spike](../../spike/README.md) and the integration test `tests/test_gateway_chart_integration.py`.
- `stateless` mode opens a fresh upstream MCP session per request, so server replicas need no sticky sessions and a restarted server recovers without client action.
- `failOpen` keeps the catalog available when one server cannot start, for example with placeholder credentials.
- Interactive elicitation (only `quantum-gaia` needs it) cannot cross a stateless multiplexing gateway, the same limitation as AgentCore.
- The [Python gateway alternative](../alternatives/python-gateway.md) stays documented in case `___` parity becomes a hard requirement.
