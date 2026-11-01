# Platform stack: the network, the EKS Auto Mode cluster and the AWS-side
# identity plumbing the workloads need. Kubernetes objects (namespaces, the
# Graviton NodePool, ESO, Reloader, the workloads) are applied by the CLI with
# kubectl/helm AFTER this stack, so Terraform never needs a live cluster
# connection at plan time.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  name       = var.prefix == "" ? "chkp-mcp-eks" : "chkp-mcp-eks-${var.prefix}"
  account_id = data.aws_caller_identity.current.account_id
  azs        = slice(data.aws_availability_zones.available.names, 0, var.az_count)
  namespace  = "chkp-mcp"
}

# ----------------------------------------------------------------------- VPC
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.7"

  name            = local.name
  cidr            = var.vpc_cidr
  azs             = local.azs
  private_subnets = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]       # /20 per AZ for pods
  public_subnets  = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 240 + i)] # /24 per AZ for the ALB

  enable_nat_gateway   = true
  single_nat_gateway   = var.single_nat_gateway
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Subnet discovery for the Auto Mode load balancer controller.
  public_subnet_tags  = { "kubernetes.io/role/elb" = "1" }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = "1" }
}

# ----------------------------------------------------------------------- EKS (Auto Mode)
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.29"

  name               = local.name
  kubernetes_version = var.kubernetes_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  endpoint_public_access       = true
  endpoint_private_access      = true
  endpoint_public_access_cidrs = var.endpoint_public_access_cidrs

  # Auto Mode: AWS runs compute (Karpenter), the ALB controller, the Pod
  # Identity agent, CoreDNS, kube-proxy and the VPC CNI. Only the `system`
  # built-in pool is enabled; workloads land on the Graviton NodePool the CLI
  # applies (the built-in general-purpose pool is amd64-only).
  compute_config = {
    enabled    = true
    node_pools = ["system"]
  }

  enable_cluster_creator_admin_permissions = true
  enable_irsa                              = false # Pod Identity instead of IRSA

  # EKS envelope-encrypts Kubernetes Secrets with an AWS-owned KMS key by
  # default. A customer-managed key is a one-line opt-in (create_kms_key +
  # encryption_config) but costs money and lingers 7-30 days after destroy.
  create_kms_key              = false
  encryption_config           = null
  enabled_log_types           = [] # control-plane logs cost money; opt in when needed
  create_cloudwatch_log_group = false

  addons = merge(
    # HPA needs the resource metrics API, which Auto Mode does not ship. It
    # tolerates the built-in system pool, so it can install with the cluster.
    { metrics-server = {} },
    # Container Insights + Fluent Bit container logs. Its controller needs a
    # general node, so on a first deploy the CLI applies this only after the
    # Graviton NodePool exists (install_cloudwatch_addon=false, then true).
    # Application Signals is off: per-signal billed, not needed here.
    var.install_cloudwatch_addon ? {
      amazon-cloudwatch-observability = {
        configuration_values = jsonencode({ applicationSignals = { enabled = false } })
        pod_identity_association = [{
          role_arn        = aws_iam_role.cloudwatch_agent.arn
          service_account = "cloudwatch-agent"
        }]
      }
    } : {}
  )
}

# ----------------------------------------------------------------------- Cognito
resource "aws_cognito_user_pool" "this" {
  name                = local.name
  deletion_protection = "INACTIVE" # destroy must leave nothing behind

  admin_create_user_config {
    allow_admin_create_user_only = true
  }
}

resource "aws_cognito_user_pool_domain" "this" {
  domain       = "${local.name}-${local.account_id}"
  user_pool_id = aws_cognito_user_pool.this.id
}

resource "aws_cognito_resource_server" "mcp" {
  identifier   = "chkp-mcp"
  name         = "Check Point MCP gateway and agent"
  user_pool_id = aws_cognito_user_pool.this.id

  scope {
    scope_name        = "invoke"
    scope_description = "Call MCP tools through the gateway and ask the agent"
  }
}

resource "aws_cognito_user_pool_client" "clients" {
  for_each = toset(["external-clients", "agent-internal"])

  name                                 = "${local.name}-${each.key}"
  user_pool_id                         = aws_cognito_user_pool.this.id
  generate_secret                      = true
  allowed_oauth_flows                  = ["client_credentials"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["${aws_cognito_resource_server.mcp.identifier}/invoke"]
  supported_identity_providers         = ["COGNITO"]
  access_token_validity                = var.token_validity_minutes
  token_validity_units {
    access_token = "minutes"
  }
  prevent_user_existence_errors = "ENABLED"
}

# The agent's own client secret, synced into the cluster by External Secrets.
resource "aws_secretsmanager_secret" "agent_client" {
  name                    = "${local.name}/agent-gateway-client"
  description             = "Cognito client credentials the agent uses to call the MCP gateway"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "agent_client" {
  secret_id = aws_secretsmanager_secret.agent_client.id
  secret_string = jsonencode({
    GATEWAY_CLIENT_ID     = aws_cognito_user_pool_client.clients["agent-internal"].id
    GATEWAY_CLIENT_SECRET = aws_cognito_user_pool_client.clients["agent-internal"].client_secret
  })
}

# Optional keys for non-Bedrock LLM providers (Azure OpenAI / OpenAI). Created
# empty; `chkpmcpeks creds apply` with an [llm] section fills it.
resource "aws_secretsmanager_secret" "llm" {
  name                    = "${local.name}/llm"
  description             = "API keys for Azure OpenAI / OpenAI-compatible LLM providers (optional)"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "llm" {
  secret_id     = aws_secretsmanager_secret.llm.id
  secret_string = jsonencode({ OPENAI_API_KEY = "", AZURE_OPENAI_API_KEY = "" })
  lifecycle {
    ignore_changes = [secret_string] # values are managed by `creds apply`, not Terraform
  }
}
