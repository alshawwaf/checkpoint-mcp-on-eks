# Example: GitOps with Argo CD or Flux

Terraform still owns the AWS side: VPC, cluster, Cognito, Pod Identity roles, certificate. The add-ons (External Secrets, Reloader), the platform manifest (`deploy/platform.yaml`) and the workload chart can then be owned by Argo CD or Flux instead of `chkpmcpeks deploy`.

1. Run `chkpmcpeks deploy` once, or `terraform apply` both stacks plus `chkpmcpeks build`. Then copy the generated values into your GitOps repository:
   - `charts/checkpoint-mcp/values-images.yaml` (image digests)
   - `charts/checkpoint-mcp/values-generated.yaml` (issuer, client ids, certificate, VPC CIDR)
2. Apply one of the manifests below. Both pin the chart to a Git revision and install it into `chkp-mcp`.

| File | Tool |
|---|---|
| [argocd-application.yaml](argocd-application.yaml) | Argo CD `Application`, multi-source: chart from this repository, values from yours |
| [flux-helmrelease.yaml](flux-helmrelease.yaml) | Flux `GitRepository` + `HelmRelease` |

Promotion between environments (dev, staging, prod) is a change to the values file in each environment's folder. Use rolling updates for the server Deployments rather than blue/green: MCP sessions live in process memory, and agentgateway's stateless mode re-opens them transparently on the next request.
