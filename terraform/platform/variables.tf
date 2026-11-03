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
    error_message = "The prefix must match [a-z][a-z0-9-]{0,11}, or be empty."
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

variable "cluster_endpoint_public_access" {
  description = "Expose the EKS API on a public endpoint as well as the private one. Off by default: the CLI reaches the private endpoint through the SSM access host."
  type        = bool
  default     = false
}

variable "cluster_endpoint_public_access_cidrs" {
  description = "CIDRs allowed to reach the public EKS API endpoint when it is enabled. No default: list your own network (the CLI fills in your current IP as a /32 for demos)."
  type        = list(string)
  default     = []

  validation {
    condition     = !var.cluster_endpoint_public_access || length(var.cluster_endpoint_public_access_cidrs) > 0
    error_message = "The public API endpoint is enabled, so cluster_endpoint_public_access_cidrs must list the networks allowed to reach it."
  }
}

variable "cluster_admin_principal_arns" {
  description = "IAM role or user ARNs that get cluster-admin through an EKS access entry: the people and pipelines that run kubectl and helm. Required; nobody is added implicitly."
  type        = list(string)

  validation {
    condition     = length(var.cluster_admin_principal_arns) > 0 && alltrue([for a in var.cluster_admin_principal_arns : can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:(role|user)/.+$", a))])
    error_message = "List at least one IAM role or user ARN, such as arn:aws:iam::123456789012:role/platform-admins. Use the role ARN, not an sts assumed-role session ARN."
  }
}

variable "enable_api_access_host" {
  description = "Create the small SSM-managed host the CLI port-forwards through to reach the private API endpoint. Turn off only if you reach the VPC another way (VPN, Direct Connect, an in-VPC runner)."
  type        = bool
  default     = true
}

variable "api_access_host_instance_type" {
  description = "Instance type of the API access host. It only relays TCP, so the smallest Graviton size is enough."
  type        = string
  default     = "t4g.nano"
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
