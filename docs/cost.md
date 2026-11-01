# Cost

Approximate on-demand prices in us-east-1, for the default deployment while it is running. Check the AWS pricing pages for your region and date.

| Item | Rate | Per day |
|---|---|---|
| EKS control plane (standard support) | USD 0.10 per hour | 2.40 |
| Graviton nodes (Auto Mode picks the size; typically 1–2 × `c7g/m7g.large`) | ~USD 0.07–0.08 per hour each | 1.70–3.90 |
| EKS Auto Mode management fee | ~12% of the EC2 price | 0.20–0.45 |
| Node EBS volumes (gp3) | ~USD 0.08 per GB-month | ~0.40 |
| Application Load Balancer | USD 0.0225 per hour + LCU | ~0.75 |
| NAT gateway | USD 0.045 per hour + USD 0.045 per GB | ~1.20 |
| Public IPv4 addresses (ALB + NAT) | USD 0.005 per hour each | ~0.36 |
| Secrets Manager (10 shared secrets + 2 stack secrets) | USD 0.40 per secret-month | ~0.16 |
| Cognito M2M tokens | USD 0.00225 per token (no per-client fee since Nov 2025) | cents |
| CloudWatch Container Insights + logs | per observation / GB | ~0.70–1.50 |
| CodeBuild, ECR storage, Amazon Nova tokens for testing | | < 0.20 |
| **Total** | | **≈ USD 8–12 per day** |

## Turning it down

- **Destroy between demos:** `python -m chkpmcpeks destroy`. A cold `deploy` takes about 30–40 minutes. Pass `--keep-images` to keep ECR, which costs cents per month, for a faster redeploy.
- **Fewer servers:** `--servers "reputation-service documentation"`. Fewer pods may fit on one node.
- **One NAT gateway** is the default (`single_nat_gateway = true`). Set it to `false` for one per AZ, which is more resilient and costs more.
- **Logs:** set a retention period on the Container Insights log groups, or disable the add-on's container logs. Control-plane logs are off by default.
- **Pool limit:** the Graviton NodePool is capped at 16 vCPU, so a runaway HPA cannot scale cost without bound.

## Never left behind

`destroy` removes every billable resource. It deletes the Helm-managed ALB before the VPC, removes CloudWatch log groups created outside Terraform, and finishes with a tag scan. Only the `chkp/<server>` secrets are kept, at USD 0.40 per secret per month, because they hold your Check Point credentials.
