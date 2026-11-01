# EKS Pod Identity: one IAM role per workload that needs AWS, each bound to a
# single Kubernetes service account. No node-wide credentials, no IRSA OIDC.

data "aws_iam_policy_document" "pod_identity_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

# ----------------------------------------------------- External Secrets Operator
# Read-only access to exactly the secrets this stack consumes: the shared
# per-server Check Point secrets (chkp/<server>) and this stack's own secrets.
data "aws_iam_policy_document" "eso" {
  statement {
    sid     = "ReadStackSecrets"
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [
      "arn:${data.aws_partition.current.partition}:secretsmanager:${var.region}:${local.account_id}:secret:${var.secret_name_prefix}*",
      "arn:${data.aws_partition.current.partition}:secretsmanager:${var.region}:${local.account_id}:secret:${local.name}/*",
    ]
  }
}

resource "aws_iam_role" "eso" {
  name               = "${local.name}-external-secrets"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
}

resource "aws_iam_role_policy" "eso" {
  name   = "read-secrets"
  role   = aws_iam_role.eso.id
  policy = data.aws_iam_policy_document.eso.json
}

resource "aws_eks_pod_identity_association" "eso" {
  cluster_name    = module.eks.cluster_name
  namespace       = "external-secrets"
  service_account = "external-secrets"
  role_arn        = aws_iam_role.eso.arn
}

# ----------------------------------------------------- Agent -> Amazon Bedrock
# Model invocation only (no AgentCore). Cross-region inference profiles route
# to foundation models in several regions, hence the region wildcard there.
locals {
  bedrock_resources = length(var.bedrock_model_arns) > 0 ? var.bedrock_model_arns : [
    "arn:${data.aws_partition.current.partition}:bedrock:*::foundation-model/*",
    "arn:${data.aws_partition.current.partition}:bedrock:*:${local.account_id}:inference-profile/*",
  ]
}

data "aws_iam_policy_document" "agent" {
  statement {
    sid       = "InvokeModels"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = local.bedrock_resources
  }
}

resource "aws_iam_role" "agent" {
  name               = "${local.name}-agent"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
}

resource "aws_iam_role_policy" "agent" {
  name   = "bedrock-invoke"
  role   = aws_iam_role.agent.id
  policy = data.aws_iam_policy_document.agent.json
}

resource "aws_eks_pod_identity_association" "agent" {
  cluster_name    = module.eks.cluster_name
  namespace       = local.namespace
  service_account = "chkp-agent"
  role_arn        = aws_iam_role.agent.arn
}

# ----------------------------------------------------- CloudWatch agent (add-on)
resource "aws_iam_role" "cloudwatch_agent" {
  name               = "${local.name}-cloudwatch-agent"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
}

resource "aws_iam_role_policy_attachment" "cloudwatch_agent" {
  role       = aws_iam_role.cloudwatch_agent.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/CloudWatchAgentServerPolicy"
}
