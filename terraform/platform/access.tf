# ----------------------------------------------------------------------- API access host
# The EKS API endpoint is private. To reach it from a workstation or a CI
# runner without a VPN, the CLI opens an AWS Systems Manager port-forward
# through this host to the private endpoint. The host:
#   * sits in a private subnet with no public IP;
#   * has NO inbound rules and no SSH key: Session Manager connects outbound;
#   * holds no Kubernetes credentials: kubectl still authenticates with the
#     caller's own IAM identity, checked against the access entries;
#   * is a t4g.nano, about USD 3 a month.
# Who may open the tunnel is governed by IAM (ssm:StartSession on this
# instance), so grant or revoke it there.

data "aws_ssm_parameter" "al2023_arm64" {
  count = var.enable_api_access_host ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

data "aws_iam_policy_document" "ec2_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api_access" {
  count              = var.enable_api_access_host ? 1 : 0
  name               = "${local.name}-api-access"
  assume_role_policy = data.aws_iam_policy_document.ec2_trust.json
}

resource "aws_iam_role_policy_attachment" "api_access_ssm" {
  count      = var.enable_api_access_host ? 1 : 0
  role       = aws_iam_role.api_access[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "api_access" {
  count = var.enable_api_access_host ? 1 : 0
  name  = "${local.name}-api-access"
  role  = aws_iam_role.api_access[0].name
}

resource "aws_security_group" "api_access" {
  count       = var.enable_api_access_host ? 1 : 0
  name        = "${local.name}-api-access"
  description = "SSM-managed relay to the private EKS API: no inbound, HTTPS out only"
  vpc_id      = module.vpc.vpc_id
}

resource "aws_vpc_security_group_egress_rule" "api_access_https" {
  count             = var.enable_api_access_host ? 1 : 0
  security_group_id = aws_security_group.api_access[0].id
  description       = "EKS API private endpoint and the Systems Manager endpoints"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "eks_api_from_access_host" {
  count                        = var.enable_api_access_host ? 1 : 0
  security_group_id            = module.eks.cluster_security_group_id
  description                  = "Kubernetes API from the SSM access host"
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  referenced_security_group_id = aws_security_group.api_access[0].id
}

resource "aws_instance" "api_access" {
  count                       = var.enable_api_access_host ? 1 : 0
  ami                         = data.aws_ssm_parameter.al2023_arm64[0].value
  instance_type               = var.api_access_host_instance_type
  subnet_id                   = module.vpc.private_subnets[0]
  vpc_security_group_ids      = [aws_security_group.api_access[0].id]
  iam_instance_profile        = aws_iam_instance_profile.api_access[0].name
  associate_public_ip_address = false

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
    encrypted   = true
  }

  tags = { Name = "${local.name}-api-access" }

  lifecycle {
    ignore_changes = [ami] # a new AL2023 release should not replace a running host
  }

  depends_on = [aws_iam_role_policy_attachment.api_access_ssm]
}
