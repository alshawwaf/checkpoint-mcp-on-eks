# Runbook: troubleshooting

Start with `python -m chkpmcpeks status`. It is read-only and reports every pod, the ALB, the 401 check, and the tool catalog. Then point kubectl at the stack:

```bash
python -m chkpmcpeks kubeconfig
```

On PowerShell, set `$env:KUBECONFIG` to the printed path. On macOS or Linux, run `export KUBECONFIG=...`.

| Symptom | Likely cause | Check / fix |
|---|---|---|
| A server pod is not Ready, or `CreateContainerConfigError` | Its Kubernetes Secret does not exist yet: the ExternalSecret has not synced. | Run `kubectl -n chkp-mcp get externalsecret`. A `SecretSyncedError` usually means the `chkp/<server>` secret is missing, or the ESO Pod Identity association is wrong (`kubectl -n external-secrets logs deploy/external-secrets`). |
| Pods `Pending` for minutes | No Graviton node yet. Auto Mode needs 1–3 minutes to launch one. | Run `kubectl get nodeclaims`, then `kubectl describe nodepool graviton`. The pool has a CPU limit of 16. |
| A server's tools missing from `tools/list` | The server failed to initialize. `failOpen` hides it instead of failing the whole catalog. | Run `kubectl -n chkp-mcp logs deploy/mcp-<server>`. With placeholder credentials most servers still list tools; `argos-erm` does not. |
| `tools/list` returns 0 tools with a valid token | Wrong client id or scope. CEL rules filter everything. | Check that the token's `client_id` is in `auth.allowedClientIds` and that `scope` contains `chkp-mcp/invoke`. |
| HTTP 401 from `/mcp` | No token, an expired token, or a token from another issuer. | `status` mints a fresh token. Compare `iss` with `auth.issuer`. |
| Tool calls error with an authentication failure from Check Point | Placeholder or wrong credentials. | Run `python -m chkpmcpeks creds apply`. See [credentials](credentials.md). |
| On-prem management times out | Firewall or source-IP allow-list. | Allow the NAT Elastic IP (**Egress IPs** in the `deploy` output). Check `serverDefaults.egress.ports`. |
| ALB has no hostname | The Auto Mode load balancer controller is still provisioning, or there are subnet tag issues. | Run `kubectl -n chkp-mcp describe ingress checkpoint-mcp`. Public subnets need the `kubernetes.io/role/elb=1` tag (Terraform sets it). |
| `/healthz` returns 502 or 504 through the ALB | Targets not yet healthy, or a NetworkPolicy blocking the ALB. | Check target health in the console. The VPC CIDR in `networkPolicy.vpcCidr` must match the real VPC. |
| `chat`: Bedrock access denied, or the use-case form message | Claude is entitled but Anthropic's one-time form is not submitted. | The agent falls back to Amazon Nova automatically. Submit the form in the Bedrock console to get Claude, with no redeploy. |
| `terraform destroy` fails on the VPC | Leftover load balancer security groups or ENIs. | `destroy` cleans these up and retries. Re-running `destroy` is safe. |

## Logs and metrics

- **CloudWatch:** Container Insights, plus log groups `/aws/containerinsights/<cluster>/application`, `/dataplane` and `/host`.
- **agentgateway metrics:** `kubectl -n chkp-mcp port-forward svc/agentgateway 15020`, then open `http://localhost:15020/metrics`.
- **Agent metrics:** `kubectl -n chkp-mcp port-forward svc/chkp-agent 8080`, then open `http://localhost:8080/metrics`.
- **Every CLI run** writes a full transcript to `~/.chkpmcpeks/logs/`.
