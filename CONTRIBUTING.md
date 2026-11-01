# Contributing

Issues and pull requests are welcome.

```bash
python -m venv .venv
```

```bash
pip install -e ".[dev]" -r services/agent/requirements.txt
```

```bash
make check
```

`make check` runs ruff, pytest (unit tests, chart parity, and the gateway integration test when
an agentgateway binary is present), `helm lint`, and `terraform fmt -check` + `validate`. CI runs
the same checks plus kubeconform, hadolint and shellcheck.

Ground rules:

- Keep `chkpmcpeks/config.py` and `charts/checkpoint-mcp/values.yaml` in sync; `tests/test_catalog_parity.py` enforces it.
- Pin everything: package versions, chart versions, image digests, GitHub Action SHAs.
- Never commit credentials. `chkp-credentials.env`, Terraform state and generated values files are gitignored.
- Any change to the gateway config must keep `tests/test_gateway_chart_integration.py` green. That test is the security regression test for header stripping and authorization.
