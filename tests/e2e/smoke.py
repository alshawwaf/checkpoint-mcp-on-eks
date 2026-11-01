"""End-to-end smoke test against a DEPLOYED stack (not part of the unit suite).

    python tests/e2e/smoke.py [--region us-east-1] [--prefix ...] [--profile ...]

Checks, through the public ALB with TLS verified:
  1. an unauthenticated MCP request is refused (401)
  2. tools/list returns the reputation-service tools as reputationservice_<tool>
  3. a reputation lookup succeeds through the gateway
  4. forged credential headers (API-KEY, MANAGEMENT-HOST) have no effect: the
     same lookup still succeeds, so the server never saw the bogus key
  5. the agent answers a reputation question by calling a reputationservice_ tool
Exit code 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from chkpmcpeks import mcpclient  # noqa: E402
from chkpmcpeks.awsutil import make_session  # noqa: E402
from chkpmcpeks.config import StackConfig  # noqa: E402
from chkpmcpeks.stack import Stack, http_json  # noqa: E402

RESULTS = []
TARGET_URL = "https://www.checkpoint.com"


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)


def url_tool(specs):
    """The reputation tool that takes a URL, and the name of that argument."""
    for name, _desc, schema in specs:
        if not name.startswith("reputationservice_"):
            continue
        props = (schema or {}).get("properties", {})
        for arg in props:
            if "url" in arg.lower() or "resource" in arg.lower():
                if "url" in name.lower():
                    return name, arg
    for name, _desc, schema in specs:   # fall back to any reputation tool with one string arg
        props = (schema or {}).get("properties", {})
        if name.startswith("reputationservice_") and len(props) >= 1:
            return name, next(iter(props))
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--prefix", default="")
    ap.add_argument("--profile", default=None)
    a = ap.parse_args()
    cfg = StackConfig(region=a.region, prefix=a.prefix)
    st = Stack(cfg, make_session(a.region, a.profile), a.profile)
    if not st.deployed:
        print("stack not deployed")
        return 1
    base, ctx = st.base_url(), st.ssl_context()
    print(f"e2e smoke against {base}")

    status, _ = http_json(f"{base}/mcp", "POST", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                   "params": {}}, ctx=ctx)
    check("unauthenticated MCP request refused", status == 401, f"HTTP {status}")

    token = st.token()
    specs = mcpclient.list_specs(f"{base}/mcp", token, ctx)
    rep = [n for n, _, _ in specs if n.startswith("reputationservice_")]
    check("reputation-service tools listed through the gateway", rep, ", ".join(rep))
    tool, arg = url_tool(specs)
    if tool:
        err, text = mcpclient.call_tool(f"{base}/mcp", token, ctx, tool, {arg: TARGET_URL})
        check(f"{tool} succeeds", not err, text[:160].replace("\n", " "))
        err2, text2 = mcpclient.call_tool(f"{base}/mcp", token, ctx, tool, {arg: TARGET_URL},
                                          extra_headers={"API-KEY": "forged-invalid-key",
                                                         "MANAGEMENT-HOST": "attacker.example"})
        check("forged API-KEY / MANAGEMENT-HOST headers have no effect", not err2 and not err,
              text2[:120].replace("\n", " "))
    else:
        check("found a reputation URL tool", False)

    body = json.dumps({"prompt": f"What is the reputation of the URL {TARGET_URL}? Use the reputation tools."})
    req = urllib.request.Request(f"{base}/v1/chat", data=body.encode(), method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=300, context=ctx) as r:
        result = json.loads(r.read().decode())
    tools_used = [t["name"] for t in result.get("tool_calls", [])]
    check("agent answered using a reputationservice_ tool",
          any(t.startswith("reputationservice_") for t in tools_used) and result.get("result"),
          f"model={result.get('model')} tools={tools_used} usage={result.get('usage')}")
    print("\nANSWER:", (result.get("result") or "")[:600])
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
