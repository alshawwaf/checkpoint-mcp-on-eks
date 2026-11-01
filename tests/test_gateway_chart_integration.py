"""Integration: the agentgateway config RENDERED BY THE HELM CHART, run by the
real agentgateway binary against fake @chkp-shaped backends.

This is the same config that runs on the cluster -- only the backend hosts and
the JWKS location are rewritten to local equivalents. Skipped unless both
`helm` and an agentgateway binary are available (AGENTGATEWAY_BIN, or the one
spike/README.md tells you to download into spike/bin/).
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys
import time

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "spike"))

from chkpmcpeks import tools  # noqa: E402

AGW = os.environ.get("AGENTGATEWAY_BIN") or next(iter(glob.glob(os.path.join(ROOT, "spike", "bin", "agentgateway*"))), "")
AGW = AGW if AGW and not AGW.endswith(".sha256") else ""
HELM = tools.find_tool("helm")

pytestmark = pytest.mark.skipif(not (AGW and HELM), reason="needs helm and an agentgateway binary")

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_SPIKE"
FAKES = {"reputationservice": 8201, "quantummanagement": 8202}


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    import run_spike as rs

    out = tmp_path_factory.mktemp("agw")
    rs.OUT = str(out)
    rs.BACKENDS = dict(FAKES)
    key = rs.make_keys()
    values = {
        "servers": {s: {"enabled": s in ("reputation-service", "quantum-management")}
                    for s in yaml.safe_load(open(os.path.join(ROOT, "charts/checkpoint-mcp/values.yaml")))["servers"]},
        "auth": {"issuer": ISSUER, "allowedClientIds": rs.CLIENTS, "resourceUrl": "http://127.0.0.1:3000/mcp"},
        "agent": {"gatewayTokenUrl": "https://example.invalid/oauth2/token"},
        "images": {"agent": {"tag": "agent-test"}},
    }
    vfile = out / "values.yaml"
    vfile.write_text(yaml.safe_dump(values))
    rendered = subprocess.run([HELM[0], "template", "t", os.path.join(ROOT, "charts/checkpoint-mcp"),
                               "-n", "chkp-mcp", "-f", str(vfile), "-s", "templates/agentgateway-config.yaml"],
                              capture_output=True, text=True, check=True).stdout
    cfg = yaml.safe_load(rendered)["data"]["config.yaml"]
    for target, port in FAKES.items():
        cfg = cfg.replace(f"http://{target}.chkp-mcp.svc.cluster.local:8000/mcp", f"http://127.0.0.1:{port}/mcp")
    cfg = cfg.replace(f"url: {ISSUER}/.well-known/jwks.json", f"file: {(out / 'jwks.json').as_posix()}")
    cfg = cfg.replace("0.0.0.0:15020", "127.0.0.1:15020").replace("0.0.0.0:15021", "127.0.0.1:15021")
    (out / "config.yaml").write_text(cfg)

    check = subprocess.run([AGW, "-f", str(out / "config.yaml"), "--validate-only"], capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr

    procs = {n: rs.start_backend(n) for n in FAKES}
    for p in FAKES.values():
        rs.wait_http(f"http://127.0.0.1:{p}/mcp")
    gw = subprocess.Popen([AGW, "-f", str(out / "config.yaml")], stdout=open(out / "agw.log", "w"),
                          stderr=subprocess.STDOUT)
    assert rs.wait_http("http://127.0.0.1:15021/healthz/ready") == 200
    time.sleep(0.5)
    yield rs, key
    gw.terminate()
    for p in procs.values():
        p.terminate()


def test_no_token_is_rejected(gateway):
    rs, _ = gateway
    status, _ = rs.http_status(rs.URL, {"Content-Type": "application/json",
                                        "Accept": "application/json, text/event-stream"},
                               b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}')
    assert status == 401


def test_catalog_is_namespaced_and_read_only(gateway):
    rs, key = gateway
    names = rs.tools_for(rs.token(key))
    assert "reputationservice_echo" in names and "quantummanagement_show_hosts" in names
    assert not any(n.endswith("add_host") for n in names)


@pytest.mark.parametrize("claims", [{"scope": "other/x"}, {"client_id": "intruder"}, {"token_use": "id"}])
def test_bad_tokens_see_nothing(gateway, claims):
    rs, key = gateway
    try:
        names = rs.tools_for(rs.token(key, **claims))
    except BaseException:  # noqa: BLE001 -- rejected at the transport
        names = []
    assert not names


def test_credential_headers_never_reach_servers(gateway):
    rs, key = gateway
    _, seen = rs.call(rs.token(key), "reputationservice_seen_headers", {},
                      {"MANAGEMENT-HOST": "attacker.example", "API-KEY": "stolen",
                       "WAF-ALLOW-WRITES": "true", "X-Anything": "1"})
    seen = set(seen.split(","))
    assert not seen & {"management-host", "api-key", "waf-allow-writes", "x-anything", "authorization"}


def test_tool_call_routes(gateway):
    rs, key = gateway
    is_error, text = rs.call(rs.token(key), "quantummanagement_echo", {"text": "hi"})
    assert not is_error and text == "quantummanagement: hi"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
