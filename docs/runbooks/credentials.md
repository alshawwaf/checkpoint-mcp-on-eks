# Runbook: Check Point credentials

The same secrets and file format as [checkpoint-mcp-on-aws-agentcore](https://github.com/alshawwaf/checkpoint-mcp-on-aws-agentcore). If you already use that project, there is nothing to migrate: this stack reuses the existing `chkp/<server>` secrets.

## The model

- Every credentialed server has its **own** Secrets Manager secret, `chkp/<server>`. Its JSON object becomes that server's environment variables.
- `deploy` creates a **placeholder** secret only for servers that have none. It never overwrites an existing secret.
- `destroy` **never deletes** `chkp/*` secrets.

## Put real credentials in

```bash
python -m chkpmcpeks creds template
```

```bash
python -m chkpmcpeks creds apply
```

Between those two commands, edit `chkp-credentials.env`. It is gitignored, with one `[server]` section of `KEY=VALUE` lines per server:

```ini
[reputation-service]
API_KEY=your-threatcloud-key

[quantum-management]
MANAGEMENT_HOST=mgmt.example.com
MANAGEMENT_PORT=443
API_KEY=your-read-only-api-key

[documentation]
CLIENT_ID=infinity-portal-client-id
SECRET_KEY=infinity-portal-secret

[llm]
# fill only the key for the provider you pick with `deploy --llm-provider`; empty lines are ignored
ANTHROPIC_API_KEY=
AZURE_OPENAI_API_KEY=
```

`apply` behaves as follows:

1. It skips any section that still holds placeholder values.
2. It writes each server's secret.
3. It annotates that server's `ExternalSecret` with `force-sync`, so External Secrets re-reads it within seconds.
4. Reloader restarts that server's pod, because env vars are read once at process start.

Values are never printed.

## Rotate one secret by hand

If you change a secret in the console or another tool, the stack picks it up within `secrets.refreshInterval` (1 minute) and Reloader restarts the pod. To force an immediate re-sync:

```bash
kubectl -n chkp-mcp annotate externalsecret mcp-reputation-service force-sync=$(date +%s) --overwrite
```

## Which fields each server needs

| Server | Fields |
|---|---|
| quantum-management, management-logs, threat-prevention, https-inspection, policy-insights, quantum-gw-cli | `MANAGEMENT_HOST`, `MANAGEMENT_PORT`, `API_KEY`, or `S1C_URL` + `API_KEY` for Smart-1 Cloud |
| reputation-service, threat-emulation | `API_KEY` (ThreatCloud) |
| documentation | `CLIENT_ID`, `SECRET_KEY` (Infinity Portal) |
| cloudguard-waf | `WAF_CLIENT_ID`, `WAF_ACCESS_KEY`, `WAF_REGION` |
| spark-management | `CLIENT_ID`, `SECRET_KEY`, `INFINITY_PORTAL_URL` |
| argos-erm | `ARGOS_API_KEY`, `ARGOS_CUSTOMER_ID` |
| harmony-sase | `API_KEY`, `MANAGEMENT_HOST`, `ORIGIN` |
| workforce-ai | `CP_CI_CLIENT_ID`, `CP_CI_ACCESS_KEY`, `CP_CI_GATEWAY` |

`quantum-gw-cli` authenticates to the **management server**, not to Gaia.

## On-prem management servers

The pods egress through the NAT gateway. Allow-list its Elastic IP, printed by `deploy` as **Egress IPs**, on the management server or the firewall in front of it. If your network requires a proxy, set `serverDefaults.proxy.httpsProxy`. If management listens on a port other than 443, add it to `serverDefaults.egress.ports`.
