# ADR 0004: Terraform in two stacks, Kubernetes objects applied after

**Status:** accepted, 2026-11-01

## Decision

Terraform owns every AWS resource, split into two root modules with different lifecycles:

- **`terraform/build`**: ECR, the CodeBuild project, the source bucket, and the optional GitHub OIDC role. Cheap, and it can outlive any cluster.
- **`terraform/platform`**: VPC, EKS Auto Mode, Cognito, Pod Identity roles, ACM, and the EKS add-ons (`metrics-server`, `amazon-cloudwatch-observability`).

It uses the `terraform-aws-modules` VPC (~> 6.7) and EKS (~> 21.29) modules plus plain resources for everything else, so each IAM statement is visible. Each `--prefix` gets its own Terraform workspace.

Kubernetes objects are applied by the CLI with kubectl and Helm **after** Terraform: the namespace, the Graviton NodePool, ESO, Reloader and the workload chart. Terraform therefore never needs a live cluster connection at plan time, a well-known source of brittle "provider depends on a resource" failures.

## eksctl, and when to use it instead

eksctl creates an EKS cluster from one YAML file, faster to write than Terraform. It covers only the cluster, so Cognito, ECR, ACM, IAM and Secrets Manager would need a second tool. Use eksctl when you only want a throwaway sandbox cluster and already have the surrounding resources. Use Terraform, the default, for anything a team will keep, review or rebuild. See [eksctl](../alternatives/eksctl.md).

## Notable choices

- No IRSA OIDC provider: **EKS Pod Identity** only.
- No customer-managed KMS key: EKS envelope-encrypts Secrets with an AWS-owned key by default. A CMK is a one-line opt-in, but it costs money and lingers 7–30 days after destroy.
- No control-plane log group by default, to save cost. Opt in with `enabled_log_types`.
- Local state by default. `backend.tf.example` shows an S3 backend with native locking (Terraform ≥ 1.10, no DynamoDB).
