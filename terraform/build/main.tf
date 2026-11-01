# Build stack: everything needed to produce the container images, with a
# lifecycle independent of the cluster (images survive a cluster rebuild).
#   - ECR repositories (immutable tags, scan on push)
#   - S3 bucket for CodeBuild source bundles
#   - CodeBuild project (arm64, native Graviton builds -- no local Docker needed)
#   - optional GitHub Actions OIDC role that can push to the same repositories

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name       = var.prefix == "" ? "chkp-mcp-eks" : "chkp-mcp-eks-${var.prefix}"
  account_id = data.aws_caller_identity.current.account_id
  registry   = "${local.account_id}.dkr.ecr.${var.region}.amazonaws.com"
  repos      = { server = "${local.name}/mcp-server", agent = "${local.name}/agent" }
}

# --------------------------------------------------------------------- ECR
resource "aws_ecr_repository" "this" {
  for_each             = local.repos
  name                 = each.value
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true # `chkpmcpeks destroy` must leave nothing behind

  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire untagged images after 7 days"
      selection    = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 7 }
      action       = { type = "expire" }
    }]
  })
}

# --------------------------------------------------------------------- source bucket
resource "aws_s3_bucket" "source" {
  bucket        = "${local.name}-build-${local.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "source" {
  bucket                  = aws_s3_bucket.source.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "source" {
  bucket = aws_s3_bucket.source.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "source" {
  bucket = aws_s3_bucket.source.id
  rule {
    id     = "expire-bundles"
    status = "Enabled"
    filter {}
    expiration {
      days = 7
    }
  }
}

# --------------------------------------------------------------------- CodeBuild
resource "aws_cloudwatch_log_group" "build" {
  name              = "/aws/codebuild/${local.name}-images"
  retention_in_days = 14
}

data "aws_iam_policy_document" "codebuild_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "codebuild" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "EcrPushPull"
    actions = [
      "ecr:BatchCheckLayerAvailability", "ecr:CompleteLayerUpload", "ecr:InitiateLayerUpload",
      "ecr:PutImage", "ecr:UploadLayerPart", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
    ]
    resources = [for r in aws_ecr_repository.this : r.arn]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.build.arn}:*"]
  }
  statement {
    sid       = "Source"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.source.arn}/*"]
  }
  statement {
    sid       = "SourceBucket"
    actions   = ["s3:GetBucketLocation", "s3:ListBucket"]
    resources = [aws_s3_bucket.source.arn]
  }
}

resource "aws_iam_role" "codebuild" {
  name               = "${local.name}-codebuild"
  assume_role_policy = data.aws_iam_policy_document.codebuild_trust.json
}

resource "aws_iam_role_policy" "codebuild" {
  name   = "build-images"
  role   = aws_iam_role.codebuild.id
  policy = data.aws_iam_policy_document.codebuild.json
}

resource "aws_codebuild_project" "images" {
  name          = "${local.name}-images"
  description   = "Builds the Check Point MCP server and agent images (arm64) into ECR"
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 60

  source {
    type      = "S3"
    location  = "${aws_s3_bucket.source.bucket}/source.zip"
    buildspec = "images/buildspec.yml"
  }

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    type            = "ARM_CONTAINER"
    image           = "aws/codebuild/amazonlinux-aarch64-standard:3.0"
    compute_type    = "BUILD_GENERAL1_SMALL"
    privileged_mode = true

    environment_variable {
      name  = "REGISTRY"
      value = local.registry
    }
    environment_variable {
      name  = "SERVER_REPO"
      value = local.repos.server
    }
    environment_variable {
      name  = "AGENT_REPO"
      value = local.repos.agent
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.build.name
    }
  }

  # IAM is eventually consistent; let the inline policy land before first use.
  depends_on = [aws_iam_role_policy.codebuild]
}
