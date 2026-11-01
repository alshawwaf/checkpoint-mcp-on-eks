# Runbook: add or remove a server

All 15 catalog servers are wired identically. Choose them with `--servers`. The `all` keyword expands to the 11 servers that work through a gateway.

```bash
python -m chkpmcpeks deploy --servers "reputation-service threat-emulation cloudguard-waf"
```

`deploy` will:

1. build any missing image;
2. create a placeholder `chkp/cloudguard-waf` secret if there is none;
3. set `servers.<name>.enabled` in `values-generated.yaml`;
4. run `helm upgrade`.

The gateway config is rendered from the same map, so the new server's tools appear as `cloudguardwaf_<tool>` in the next `tools/list`. Removing a server from `--servers` removes its Deployment, Service, ExternalSecret and gateway target, but keeps its secret.

## Adding a server that is not in the catalog

1. Add it to `SERVER_CATALOG` in `chkpmcpeks/config.py`, with its pinned version, credential shape and startup args.
2. Add the same entry to `servers:` in `charts/checkpoint-mcp/values.yaml`. `tests/test_catalog_parity.py` fails until both match.
3. If its package reads credentials from new request headers, add those names to `CHKP_CREDENTIAL_HEADERS` and `agentgateway.denyHeaders`. The header allow-list already blocks them, so this is defense in depth.
4. Run `pytest`, then `python -m chkpmcpeks deploy --servers "... new-server"`.

## Servers with caveats

| Server | Caveat |
|---|---|
| argos-erm | Cannot list tools without real Argos credentials, so it is excluded from `all`. |
| harmony-sase, workforce-ai | Tenant-specific credentials, not yet validated on this stack, so excluded from `all`. |
| quantum-gaia | Interactive-only login that cannot cross a gateway, so excluded from `all`. |
| threat-emulation | Remote hash and URL lookups only; local file upload does not apply. |
| documentation | Needs `--region US`, set automatically. |
