# Alternatives

The defaults are chosen for a clean, cheap, reproducible demo that still follows production practice. Each alternative below is a supported swap, with what changes.

## Gateway: purpose-built Python gateway instead of agentgateway

Choose this only if exact `server___tool` naming parity with the AgentCore project is a hard requirement. Build it on the official `mcp` SDK (≥ 2.3): a low-level `Server` with `on_list_tools` / `on_call_tool` aggregating backend sessions, and `StreamableHTTPSessionManager(stateless=True)` toward clients. It must also include PyJWT + JWKS validation, the same header allow-list, `/healthz` and `/readyz`, and Prometheus metrics. The trade-off is that you own MCP spec drift, SDK majors and the auth code. Set `TOOL_SEPARATOR=___` on the agent. See [ADR 0001](../adr/0001-mcp-gateway.md).

## Auth: Keycloak instead of Cognito

Run Keycloak (for example the Bitnami or codecentric chart, backed by Amazon RDS for PostgreSQL). Create a realm, a confidential client with the client-credentials grant, and a client scope `chkp-mcp/invoke` mapped into the `scope` claim. Then set `auth.issuer`, `auth.jwksUrl`, `auth.audience` and `agent.gatewayTokenUrl` as in [bring your own platform](../runbooks/bring-your-own-platform.md). agentgateway also supports `mcpAuthentication.provider.keycloak` if you want MCP clients to run the OAuth flow themselves.

## Compute: managed node groups instead of EKS Auto Mode

In `terraform/platform/main.tf`, replace `compute_config` with an `eks_managed_node_groups` block (Graviton `m7g.large`, min 1, max 3). Add the `eks-pod-identity-agent`, `vpc-cni`, `coredns` and `kube-proxy` add-ons. Install the AWS Load Balancer Controller with Helm, using its own Pod Identity role. Then change the chart:

- `IngressClass.controller` to `ingress.k8s.aws/alb`;
- replace `IngressClassParams` with `alb.ingress.kubernetes.io/*` annotations (`certificate-arn`, `scheme`, `inbound-cidrs`);
- install a NetworkPolicy engine: enable the VPC CNI network policy agent.

Remove the Graviton `NodePool` from `deploy/platform.yaml`. This path is cheaper per node (no Auto Mode fee), but you patch and upgrade the nodes and add-ons yourself.

## Cluster tooling: eksctl instead of Terraform

```bash
eksctl create cluster --name chkp-mcp-eks --region us-east-1 --enable-auto-mode
```

Then create the Pod Identity associations with `eksctl create podidentityassociation`, and Cognito, ACM and ECR by hand or with another tool. Use this for a throwaway sandbox when the surrounding resources already exist. For anything a team will keep, review or rebuild, Terraform is the better fit. See [ADR 0004](../adr/0004-infrastructure-as-code.md).

## TLS without a domain: CloudFront in front of the ALB

Add a CloudFront distribution with the ALB as an origin over HTTPS, a secret custom header that the ALB rule requires, and caching disabled. It forwards `Authorization`, `Accept`, `Content-Type` and the `Mcp-*` headers. The distribution's `*.cloudfront.net` certificate is publicly trusted, so desktop MCP clients work without your own domain. Verify SSE streaming end to end, and keep the origin-header check so nobody can bypass CloudFront.

## Secrets: Secrets Store CSI Driver instead of External Secrets

Install the CSI driver and the AWS provider, then mount `chkp/<server>` with `syncSecret` enabled to get a Kubernetes Secret for `envFrom`. It works, but it adds a DaemonSet and a volume per pod to do what ESO does natively. See [ADR 0003](../adr/0003-secrets.md).

## Observability: Prometheus and Grafana instead of CloudWatch

Install kube-prometheus-stack in a `monitoring` namespace and set `podMonitors.enabled: true`. The NetworkPolicies already allow scraping from `monitoring`. For traces, point `agentgateway.tracing.otlpEndpoint` at an OpenTelemetry Collector.
