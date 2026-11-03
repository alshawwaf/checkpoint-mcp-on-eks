# ADR 0008: Private Kubernetes API, explicit cluster admins

**Status:** accepted, 2026-11-02. Supersedes the public-endpoint and creator-admin defaults of ADR 0004.

## Context

A cloud security review of the first release flagged three cluster defaults:

- the EKS API endpoint was public;
- its allowed CIDRs defaulted to `0.0.0.0/0`;
- whoever ran Terraform became cluster admin implicitly.

Each one made the one-command deploy simpler, and none is AWS best practice for a cluster that holds security-tool credentials.

## Decision

- **Private API endpoint by default.** `cluster_endpoint_public_access` defaults to `false`. A public endpoint is an explicit opt-in, and its CIDR list has no default. Terraform rejects an enabled public endpoint with an empty list. The CLI's `--public-endpoint` fills in the caller's IP as a /32 and labels it a demo convenience.
- **An SSM access host instead of a VPN.** A `t4g.nano` host in a private subnet has no inbound rules, no SSH key, IMDSv2 only, and no Kubernetes credentials. The CLI starts a Systems Manager port-forward through it to the private endpoint, using boto3 and the Session Manager plugin, with no AWS CLI. It writes a kubeconfig that points at the local end and still verifies TLS against the real endpoint name. `deploy`, `status`, `creds apply` and `destroy` open the tunnel on their own. `chkpmcpeks tunnel` holds it open for an operator's own `kubectl`.
- **Explicit access entries.** `enable_cluster_creator_admin_permissions = false`, the module keeps `bootstrap_cluster_creator_admin_permissions` off, and `authentication_mode = "API"`. The required variable `cluster_admin_principal_arns` lists who gets `AmazonEKSClusterAdminPolicy` at cluster scope. Terraform itself never calls the Kubernetes API, so its own identity needs no Kubernetes access. The CLI asks before adding the caller, and CI passes `--admin-arn`.
- **Client commands skip the Kubernetes API.** `chat`, `endpoints` and `token` find the ALB through the ELB API, so they work without a tunnel.

## Alternatives considered

- **Run the Kubernetes steps from CodeBuild inside the VPC.** It needs no extra local tool, but every `kubectl` interaction, including `status` and troubleshooting, would become a remote job. Rejected for operability.
- **A VPN or Client VPN endpoint.** Right for teams that already have one, which is why `enable_api_access_host = false` exists. Too heavy as the default for a reproducible reference.
- **A public endpoint limited to the deployer's IP.** Kept as the opt-in demo path, not the default.

## Consequences

- The Session Manager plugin is a new prerequisite. `doctor` checks for it and prints the install line.
- The access host adds about USD 3 a month while the stack runs. IAM `ssm:StartSession` on that instance decides who may open a tunnel.
- First-time `deploy` asks one more question, or needs `--admin-arn` in non-interactive runs.
