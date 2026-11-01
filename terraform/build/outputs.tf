output "registry" {
  description = "ECR registry hostname."
  value       = local.registry
}

output "server_repository" {
  description = "ECR repository for the MCP server images (one tag per server-version)."
  value       = aws_ecr_repository.this["server"].name
}

output "agent_repository" {
  description = "ECR repository for the agent image."
  value       = aws_ecr_repository.this["agent"].name
}

output "source_bucket" {
  description = "S3 bucket CodeBuild reads its source bundle from."
  value       = aws_s3_bucket.source.bucket
}

output "codebuild_project" {
  description = "CodeBuild project that builds the images."
  value       = aws_codebuild_project.images.name
}
