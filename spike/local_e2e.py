"""Local end-to-end: agent (real Amazon Bedrock) -> agentgateway (JWT + policy)
-> fake MCP backends. Proves the agent loop, the gateway naming and auth, and
a live model round-trip from the workstation before anything runs on EKS.

    python spike/local_e2e.py
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "services", "agent"))

import run_spike as rs  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from chkp_agent.app import create_app  # noqa: E402
from chkp_agent.settings import Settings  # noqa: E402


class StaticToken:
    def __init__(self, tok):
        self.tok = tok

    def get(self):
        return self.tok


def main():
    os.makedirs(rs.OUT, exist_ok=True)
    key = rs.make_keys()
    cfg = os.path.join(rs.OUT, "agw-config.yaml")
    with open(cfg, "w") as fh:
        fh.write(rs.render_config())
    procs = {n: rs.start_backend(n) for n in rs.BACKENDS}
    for p in rs.BACKENDS.values():
        rs.wait_http(f"http://127.0.0.1:{p}/mcp")
    gw = subprocess.Popen([rs.AGW, "-f", cfg], stdout=open(os.path.join(rs.OUT, "agw-e2e.log"), "w"),
                          stderr=subprocess.STDOUT)
    try:
        rs.wait_http("http://127.0.0.1:15021/healthz/ready")
        settings = Settings(auth_disabled=True, gateway_url=rs.URL, provider="bedrock",
                            model=os.environ.get("LLM_MODEL", ""), aws_region="us-east-1")
        client = TestClient(create_app(settings, token_provider=StaticToken(rs.token(key))))
        prompts = ["Use the fakeb show_hosts tool and list the hosts it returns.",
                   "Call the fakea echo tool with the text 'ping' and tell me exactly what it returned."]
        ok = True
        for prompt in prompts:
            r = client.post("/v1/chat", json={"prompt": prompt})
            body = r.json()
            tools = [t["name"] for t in body.get("tool_calls", [])]
            print(f"\nQ: {prompt}\nHTTP {r.status_code} model={body.get('model')} tools={tools}")
            print(f"A: {body.get('result') or body.get('detail')}")
            print(f"usage={body.get('usage')} cache_hit={body.get('cache_hit_pct')}% in {body.get('seconds')}s")
            ok &= r.status_code == 200 and bool(tools) and not body.get("error")
        print("\nLOCAL E2E", "PASSED" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        gw.terminate()
        for p in procs.values():
            p.terminate()


if __name__ == "__main__":
    sys.exit(main())
