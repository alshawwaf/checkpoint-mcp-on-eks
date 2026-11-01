# Why EKS instead of Bedrock AgentCore, and when AgentCore is still the better pick

Both projects run the same 15 `@chkp` MCP servers behind one authenticated gateway, with the same secrets and the same security-operations agent. They differ in **who runs the plumbing**.

| | Bedrock AgentCore ([sibling project](https://github.com/alshawwaf/checkpoint-mcp-on-aws-agentcore)) | Amazon EKS (this repo) |
|---|---|---|
| **MCP servers run as** | AgentCore Runtimes (serverless containers) | Kubernetes Deployments on Graviton nodes |
| **Gateway** | AgentCore Gateway (managed) | agentgateway (open source, Linux Foundation) in the cluster |
| **Tool names** | `server___tool` | `server_tool` (separator configurable in the agent) |
| **Inbound auth** | Cognito JWT at the gateway | Cognito JWT at the gateway and at the agent; any OIDC issuer |
| **Policy** | AgentCore Policy (Cedar), Bedrock Guardrails | CEL rules in agentgateway (client, scope, per-tool read-only), Kubernetes NetworkPolicies |
| **Network control** | Public runtimes, or VPC mode | Private subnets, default-deny NetworkPolicies, one NAT egress IP to allow-list |
| **LLM** | Bedrock (Claude, Nova) | Bedrock by default; Azure OpenAI or any OpenAI-compatible endpoint by config |
| **Portability** | AWS only, AgentCore regions only | Any conformant Kubernetes; the chart and images run on EKS, AKS, GKE or on-prem with config changes |
| **Delivery** | One Python CLI calling AWS APIs | Terraform + Helm + images by digest, GitOps-ready, plus the same one-command CLI |
| **Idle cost** | Near zero: runtimes scale to zero, you pay per use | About USD 10–12/day while the cluster exists (control plane, nodes, NAT, ALB) |
| **Ops burden** | Lowest: no nodes, no cluster upgrades | Moderate. Auto Mode removes node and add-on toil, but you still own Kubernetes upgrades, the chart and policies. |
| **Cold start** | Runtime spin-up on the first call after idle | None: pods are always warm |

## Choose EKS when

- You already run Kubernetes, and platform, security and SRE teams want MCP workloads on the **same** cluster tooling: GitOps, admission policy, service mesh, central logging.
- You need **portability**: the same chart on another cloud or on-prem, or a model provider other than Bedrock (Azure OpenAI, self-hosted).
- **Network control** matters: private subnets, a single egress IP for on-prem management servers, NetworkPolicies, a corporate egress proxy, Vault for secrets.
- You want to inspect, patch or replace every component, including the gateway, and pin everything by digest.
- Steady traffic makes always-on capacity cost-effective, or you want zero cold starts.

## Choose AgentCore when

- You want the **least operational work**: no cluster, no nodes, no upgrades, scale to zero.
- Usage is spiky or low, so per-use pricing beats an always-on cluster.
- You want AWS-native agent features out of the box: AgentCore Memory, the AgentCore Policy engine with Bedrock Guardrails, managed identity for outbound calls.
- The team is AWS-centric and has no Kubernetes expertise or appetite.

## Moving between them

Credentials carry over unchanged. Both use `chkp/<server>` secrets and the same `chkp-credentials.env` format, and neither project's teardown deletes those secrets. The agent's prompts and loop are shared; only the tool separator differs. You can run both stacks in the same account at the same time.
