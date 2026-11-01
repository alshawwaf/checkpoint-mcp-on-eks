output "cluster_name" {
  value = module.eks.cluster_name
}

output "region" {
  value = var.region
}

output "namespace" {
  value = local.namespace
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "vpc_cidr" {
  value = var.vpc_cidr
}

output "nat_public_ips" {
  description = "Egress IPs of the cluster -- allow-list these on on-prem management servers."
  value       = module.vpc.nat_public_ips
}

output "certificate_arn" {
  value = local.certificate_arn
}

output "self_signed_cert_pem" {
  description = "PEM of the self-signed ALB certificate (empty when a real domain is used). Public, not secret."
  value       = local.use_domain ? "" : tls_self_signed_cert.alb[0].cert_pem
}

output "domain_name" {
  value = var.domain_name
}

output "alb_inbound_cidrs" {
  value = var.alb_inbound_cidrs
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.this.id
}

output "cognito_issuer" {
  value = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.this.id}"
}

output "cognito_jwks_url" {
  value = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.this.id}/.well-known/jwks.json"
}

output "cognito_token_url" {
  value = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${var.region}.amazoncognito.com/oauth2/token"
}

output "cognito_scope" {
  value = "${aws_cognito_resource_server.mcp.identifier}/invoke"
}

output "external_client_id" {
  description = "Client id for external MCP clients and the CLI (secret: read it from Cognito, never printed)."
  value       = aws_cognito_user_pool_client.clients["external-clients"].id
}

output "agent_client_id" {
  value = aws_cognito_user_pool_client.clients["agent-internal"].id
}

output "agent_client_secret_name" {
  value = aws_secretsmanager_secret.agent_client.name
}

output "llm_secret_name" {
  value = aws_secretsmanager_secret.llm.name
}

output "secret_name_prefix" {
  value = var.secret_name_prefix
}

output "certificate_validation_records" {
  description = "DNS records that prove domain ownership to ACM (create them at your DNS provider when Route 53 is not used)."
  value = local.use_domain ? [
    for o in aws_acm_certificate.domain[0].domain_validation_options : {
      name  = o.resource_record_name
      type  = o.resource_record_type
      value = o.resource_record_value
    }
  ] : []
}

output "route53_zone_id" {
  value = var.route53_zone_id
}
