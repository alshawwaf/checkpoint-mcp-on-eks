# Optional: let GitHub Actions push images to ECR with short-lived OIDC
# credentials instead of stored AWS keys. Enabled by setting
# github_repository = "owner/name". The role can ONLY push to this stack's two
# repositories, and only from workflows running on the main branch.

variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to push images via OIDC. Empty disables."
  type        = string
  default     = ""
}

variable "create_github_oidc_provider" {
  description = "Create the account-wide GitHub OIDC provider (set false if the account already has one)."
  type        = bool
  default     = true
}

locals {
  github_enabled = var.github_repository != ""
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = local.github_enabled && var.create_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "github" {
  count = local.github_enabled && !var.create_github_oidc_provider ? 1 : 0
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  github_provider_arn = !local.github_enabled ? "" : (
    var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
  )
}

data "aws_iam_policy_document" "github_trust" {
  count = local.github_enabled ? 1 : 0
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

data "aws_iam_policy_document" "github_push" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:CompleteLayerUpload", "ecr:InitiateLayerUpload",
      "ecr:PutImage", "ecr:UploadLayerPart", "ecr:BatchGetImage", "ecr:DescribeImages",
    ]
    resources = [for r in aws_ecr_repository.this : r.arn]
  }
}

resource "aws_iam_role" "github" {
  count              = local.github_enabled ? 1 : 0
  name               = "${local.name}-github-actions"
  assume_role_policy = data.aws_iam_policy_document.github_trust[0].json
}

resource "aws_iam_role_policy" "github" {
  count  = local.github_enabled ? 1 : 0
  name   = "push-images"
  role   = aws_iam_role.github[0].id
  policy = data.aws_iam_policy_document.github_push.json
}

output "github_actions_role_arn" {
  description = "Set as the repository variable AWS_ROLE_ARN to enable .github/workflows/build-images.yml."
  value       = local.github_enabled ? aws_iam_role.github[0].arn : ""
}
