# ADR 0006: CloudWatch Container Insights by default, Prometheus-ready

**Status:** accepted, 2026-11-01

## Decision

- **Default:** the `amazon-cloudwatch-observability` EKS add-on, with Pod Identity and `CloudWatchAgentServerPolicy`. It provides Container Insights metrics and Fluent Bit container logs with no extra pods for you to manage. **Application Signals is disabled**, since it is per-signal billed and the demo does not need it.
- **Structured logs:** agentgateway logs JSON. The agent logs one JSON object per line and records prompt **length** only, never tokens, headers or tool arguments.
- **Metrics:**
  - agentgateway exposes Prometheus metrics on `:15020/metrics`, including per-backend MCP request counts and latency.
  - The agent exposes `chkp_agent_requests_total`, `chkp_agent_tool_calls_total{tool,error}`, `chkp_agent_tokens_total{kind}` and `chkp_agent_request_seconds` on `/metrics`.
- **Traces:** set `agentgateway.tracing.otlpEndpoint` to send OpenTelemetry spans to any collector.

## Why not kube-prometheus-stack by default

It adds six or more pods and persistent storage to a two-node demo. Teams that already run Prometheus can enable `podMonitors.enabled`. The NetworkPolicies already allow scraping from the `monitoring` and `amazon-cloudwatch` namespaces.
