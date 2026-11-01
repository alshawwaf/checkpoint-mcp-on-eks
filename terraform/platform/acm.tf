# TLS for the ALB.
#
# No domain (default): a self-signed certificate valid for the ALB's own
# hostname (*.<region>.elb.amazonaws.com) is generated and imported into ACM.
# The CLI and tests trust it explicitly through the exported PEM, so TLS stays
# fully verified; desktop MCP clients need the real-domain path below.
#
# With domain_name + route53_zone_id: a public ACM certificate, DNS-validated.
# The CLI points domain_name at the ALB after it exists (or use external-dns).

locals {
  use_domain   = var.domain_name != ""
  alb_wildcard = "*.${var.region}.elb.amazonaws.com"
  # Always kept (free): switching to a real domain must never delete a
  # certificate the ALB is still using. The ALB moves to the domain cert first.
  self_signed_n = 1
}

resource "tls_private_key" "alb" {
  count     = local.self_signed_n
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "alb" {
  count           = local.self_signed_n
  private_key_pem = tls_private_key.alb[0].private_key_pem

  subject {
    common_name  = local.alb_wildcard
    organization = "Check Point MCP on EKS (self-signed demo)"
  }
  dns_names             = [local.alb_wildcard]
  validity_period_hours = 24 * 365
  early_renewal_hours   = 24 * 30
  allowed_uses          = ["key_encipherment", "digital_signature", "server_auth"]
}

resource "aws_acm_certificate" "self_signed" {
  count            = local.self_signed_n
  private_key      = tls_private_key.alb[0].private_key_pem
  certificate_body = tls_self_signed_cert.alb[0].cert_pem

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate" "domain" {
  count             = local.use_domain ? 1 : 0
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "validation" {
  for_each = local.use_domain && var.route53_zone_id != "" ? {
    for o in aws_acm_certificate.domain[0].domain_validation_options : o.domain_name => o
  } : {}

  zone_id = var.route53_zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  records = [each.value.resource_record_value]
  ttl     = 300
}

resource "aws_acm_certificate_validation" "domain" {
  count                   = local.use_domain && var.route53_zone_id != "" ? 1 : 0
  certificate_arn         = aws_acm_certificate.domain[0].arn
  validation_record_fqdns = [for r in aws_route53_record.validation : r.fqdn]
}

locals {
  certificate_arn = local.use_domain ? aws_acm_certificate.domain[0].arn : aws_acm_certificate.self_signed[0].arn
}
