# Runbook: teardown

```bash
python -m chkpmcpeks destroy
```

The command lists what it will remove and asks for confirmation. Pass `--yes` in non-interactive shells. It works in the order EKS needs:

1. **Uninstall the Helm release.** The Auto Mode controller deletes the ALB and its security groups.
2. **Wait until no load balancer remains** in the stack's VPC.
3. **Remove the add-ons and the Graviton NodePool.** Reloader and External Secrets go first, then the NodePool, so the nodes terminate.
4. **Run `terraform destroy` on the platform stack:** cluster, VPC, NAT, Cognito, IAM roles, ACM certificate, and this stack's own secrets (recovery window 0). If the VPC still holds orphaned security groups or ENIs, they are removed and the destroy is retried once.
5. **Delete the CloudWatch log groups** the observability add-on created outside Terraform.
6. **Run `terraform destroy` on the build stack:** ECR repositories with their images, the CodeBuild project, the source bucket. Pass `--keep-images` to skip this step and make the next deploy faster.
7. **Scan for leftovers:** anything still tagged `project=chkp-mcp-eks`. The tagging API can lag a few minutes; re-run to confirm.

**Kept by design:** the `chkp/<server>` Check Point credential secrets. They hold your credentials and may be shared with the AgentCore deployment. To remove one deliberately:

```bash
python -c "import boto3; boto3.client('secretsmanager').delete_secret(SecretId='chkp/reputation-service', RecoveryWindowInDays=7)"
```

Every step is idempotent. If a destroy is interrupted, run it again.
