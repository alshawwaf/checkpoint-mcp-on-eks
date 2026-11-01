# Runbook: upgrades

Everything is pinned. Upgrade one thing at a time and re-run the tests.

| What | Where it is pinned | After bumping |
|---|---|---|
| A `@chkp` server | `SERVER_CATALOG` in `chkpmcpeks/config.py` **and** `servers:` in `values.yaml` | Re-extract its header names (below). `python -m chkpmcpeks deploy` builds the new tag and rolls the pod. |
| agentgateway | `agentgateway.image` (tag + digest) in `values.yaml`, `AGENTGATEWAY_VERSION` in `ci.yml` | Run `spike/run_spike.py` and `pytest tests/test_gateway_chart_integration.py` with the new binary. |
| External Secrets, Reloader | `ADDONS` in `chkpmcpeks/kube.py` | `deploy` runs `helm upgrade` on them. |
| EKS version | `kubernetes_version` in `terraform/platform/variables.tf` | Upgrade one minor version at a time. Auto Mode rolls the nodes. |
| Terraform modules and providers | `terraform/*/versions.tf`, `main.tf`, `.terraform.lock.hcl` | `terraform init -upgrade`, then `plan` and review. |
| Agent dependencies | `services/agent/requirements.txt` | `pytest`. The agent image tag changes automatically, because it is a content hash. |
| GitHub Actions | SHA pins in `.github/workflows/*.yml` | Dependabot opens PRs. |

## Re-extracting `@chkp` header names (security)

agentgateway's header allow-list already keeps every non-protocol header away from the servers. The deny-list is a second layer and must list what the packages read. After bumping a server version, run this from a clone of `CheckPointSW/mcp-servers` at the new tag:

```bash
grep -rhoE "getHeaderValue\([^,]+, *['\"][^'\"]+['\"]" packages/*/src | grep -oE "['\"][^'\"]+['\"]$" | tr -d "'\"" | tr 'A-Z' 'a-z' | sort -u
```

Add any new names to `CHKP_CREDENTIAL_HEADERS` in `config.py` and `agentgateway.denyHeaders` in `values.yaml`. CI checks they match.
