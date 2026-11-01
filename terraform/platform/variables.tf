variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "prefix" {
  description = "Optional short prefix to run a second, independent stack in the same account."
  type        = string
  default     = ""

  validation {
    condition     = can(regex("^([a-z][a-z0-9-]{0,11})?$", var.prefix))
    error_message = "prefix must match [a-z][a-z0-9-]{0,11} or be empty."
  }
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.37"
}

variable "vpc_cidr" {
  description = "CIDR for the new VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "az_count" {
  description = "Availability zones to span (2 is the minimum EKS accepts)."
  type        = number
  default     = 2
}

variable "single_nat_gateway" {
  description = "One shared NAT gateway (cheap, one AZ dependency) or one per AZ (resilient)."
  type        = bool
  default     = true
}

variable "endpoint_public_access_cidrs" {
  description = "CIDRs allowed to reach the public EKS API endpoint. Restrict this to your network."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "alb_inbound_cidrs" {
  description = "CIDRs allowed to reach the public ALB (MCP gateway + agent API)."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "domain_name" {
  description = "Optional DNS name for the ALB (e.g. mcp.example.com). Empty = self-signed certificate for the ALB's own hostname."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Route 53 hosted zone for domain_name (needed for DNS validation and the alias record)."
  type        = string
  default     = ""
}

variable "secret_name_prefix" {
  description = "Secrets Manager prefix of the per-server Check Point secrets (shared with the AgentCore project)."
  type        = string
  default     = "chkp/"
}

variable "bedrock_model_arns" {
  description = "Bedrock models/inference profiles the agent may invoke. Default: any foundation model and any inference profile in this account."
  type        = list(string)
  default     = []
}

variable "token_validity_minutes" {
  description = "Lifetime of Cognito access tokens issued to MCP/agent clients."
  type        = number
  default     = 60
}

variable "extra_tags" {
  description = "Additional tags applied to every resource."
  type        = map(string)
  default     = {}
}

variable "install_cloudwatch_addon" {
  description = "Install the CloudWatch Observability add-on. The CLI sets false on a first deploy until the Graviton NodePool exists."
  type        = bool
  default     = true
}
