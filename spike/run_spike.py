"""Phase 1 spike: does standalone agentgateway do what the EKS design needs?

Starts two fake @chkp-shaped MCP backends and agentgateway (with a config
shaped like the Helm chart's), then checks:

  1. no token -> 401                      6. client-supplied MANAGEMENT-HOST /
  2. tools/list -> <target>_<tool> names      API-KEY headers never reach backends
  3. read-only policy hides add_host      7. one backend down -> others still served
  4. wrong scope / wrong client -> denied 8. backend restart -> calls recover
  5. tools/call routes to the right target 9. Prometheus metrics are exposed

    python spike/run_spike.py [path-to-agentgateway-binary]
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
PY = sys.executable
AGW = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "bin", "agentgateway-windows-amd64.exe")
ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_SPIKE"
SCOPE = "chkp-mcp/invoke"
CLIENTS = ["agent-internal-id", "external-clients-id"]
URL = "http://127.0.0.1:3000/mcp"
BACKENDS = {"fakea": 8101, "fakeb": 8102}
sys.path.insert(0, os.path.join(HERE, ".."))
from chkpmcpeks.config import MUTATING_TOOL_PATTERNS  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)


# --------------------------------------------------------------------------- keys / tokens
def b64u(n):
    return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).decode().rstrip("=")


def make_keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    jwks = {"keys": [{"kty": "RSA", "kid": "spike", "use": "sig", "alg": "RS256",
                      "n": b64u(pub.n), "e": b64u(pub.e)}]}
    with open(os.path.join(OUT, "jwks.json"), "w") as fh:
        json.dump(jwks, fh)
    return key


def token(key, client_id=CLIENTS[0], scope=SCOPE, issuer=ISSUER, token_use="access"):
    now = int(time.time())
    claims = {"sub": client_id, "client_id": client_id, "scope": scope, "iss": issuer,
              "token_use": token_use, "iat": now, "exp": now + 600, "jti": str(now)}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "spike"})


# --------------------------------------------------------------------------- config
# Only these request headers may reach a backend. Everything else -- notably the
# @chkp credential headers (API-KEY, MANAGEMENT-HOST, WAF-ALLOW-WRITES, ...) -- is
# dropped. Authorization is consumed by the gateway and never forwarded.
FORWARD_HEADERS = ("accept", "content-type", "mcp-protocol-version", "mcp-session-id",
                   "last-event-id", "mcp-method", "mcp-name")


def header_policy_block(kind):
    if kind == "none":
        return ""
    if kind == "denylist":
        from chkpmcpeks.config import CHKP_CREDENTIAL_HEADERS
        names = ", ".join(CHKP_CREDENTIAL_HEADERS)
        return f"        requestHeaderModifier:\n          remove: [{names}]"
    # Rebuild the header map from the allow-list; a header the client did not
    # send becomes an empty list (= not sent).
    entries = ", ".join(f'"{h}": ("{h}" in request.headers) ? request.headers["{h}"] : []'
                        for h in FORWARD_HEADERS)
    expr = os.environ.get("REPLACE_EXPR") or "{" + entries + "}"
    return ("        transformations:\n          request:\n            replace: |\n"
            f"              {expr}")

def render_config():
    """Mirror of charts/checkpoint-mcp/templates/agentgateway-config.yaml."""
    mutating = " || ".join(f'mcp.tool.name.contains("{p}")' for p in MUTATING_TOOL_PATTERNS)
    clients = ", ".join(f'"{c}"' for c in CLIENTS)
    targets = "\n".join(f"          - name: {n}\n            mcp:\n              host: http://127.0.0.1:{p}/mcp"
                        for n, p in BACKENDS.items())
    jwks = os.path.join(OUT, "jwks.json").replace("\\", "/")
    header_policy = header_policy_block(os.environ.get("HEADER_POLICY", "both"))
    return f"""# spike config -- mirrors the Helm chart
config:
  adminAddr: 127.0.0.1:15000
  statsAddr: 127.0.0.1:15020
  readinessAddr: 127.0.0.1:15021
  logging:
    format: json
binds:
- port: 3000
  listeners:
  - routes:
    - name: mcp
      matches:
      - path:
          pathPrefix: /mcp
      policies:
{header_policy}
        mcpAuthentication:
          mode: strict
          issuer: {ISSUER}
          jwks:
            file: {jwks}
          resourceMetadata:
            resource: {URL}
            scopesSupported: ["{SCOPE}"]
            bearerMethodsSupported: [header]
        mcpAuthorization:
          rules:
          - require: 'jwt.token_use == "access"'
          - require: 'jwt.client_id in [{clients}]'
          - require: '(" " + jwt.scope + " ").contains(" {SCOPE} ")'
          - allow: '!({mutating})'
      backends:
      - mcp:
          prefixMode: always
          statefulMode: stateless
          failureMode: failOpen
          targets:
{targets}
"""


# --------------------------------------------------------------------------- processes
def start_backend(name):
    return subprocess.Popen([PY, os.path.join(HERE, "fake_mcp.py"), name, str(BACKENDS[name])],
                            stdout=open(os.path.join(OUT, f"{name}.log"), "w"), stderr=subprocess.STDOUT)


def wait_http(url, attempts=60):
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except OSError:
            time.sleep(0.5)
    return None


def http_status(url, headers=None, body=None):
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


# --------------------------------------------------------------------------- MCP client
async def mcp_session(tok, extra_headers=None, fn=None):
    headers = {"Authorization": f"Bearer {tok}", **(extra_headers or {})}
    async with create_mcp_http_client(headers=headers) as http:
        async with streamable_http_client(URL, http_client=http) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return await fn(s)


async def list_names(s):
    res = await s.list_tools()
    return sorted(t.name for t in res.tools)


def tools_for(tok):
    return asyncio.run(mcp_session(tok, fn=list_names))


def call(tok, tool, args=None, headers=None):
    async def _c(s):
        r = await s.call_tool(tool, args or {})
        text = " ".join(getattr(b, "text", "") for b in r.content)
        return r.is_error, text
    return asyncio.run(mcp_session(tok, headers, _c))


def safe(fn, *a, **kw):
    try:
        return fn(*a, **kw), None
    except BaseException as e:  # noqa: BLE001 -- anyio wraps errors in groups
        return None, f"{type(e).__name__}: {str(e)[:200]}"


# --------------------------------------------------------------------------- main
def main():
    os.makedirs(OUT, exist_ok=True)
    key = make_keys()
    cfg_path = os.path.join(OUT, "agw-config.yaml")
    with open(cfg_path, "w") as fh:
        fh.write(render_config())

    rc = subprocess.run([AGW, "-f", cfg_path, "--validate-only"], capture_output=True, text=True)
    check("config validates", rc.returncode == 0, (rc.stdout + rc.stderr).strip()[-400:])
    if rc.returncode:
        return 1

    procs = {n: start_backend(n) for n in BACKENDS}
    for n, p in BACKENDS.items():
        wait_http(f"http://127.0.0.1:{p}/mcp")
    gw = subprocess.Popen([AGW, "-f", cfg_path], stdout=open(os.path.join(OUT, "agw.log"), "w"),
                          stderr=subprocess.STDOUT)
    try:
        ready = wait_http("http://127.0.0.1:15021/healthz/ready")
        check("readiness endpoint", ready == 200, f"HTTP {ready}")
        good = token(key)

        status, _ = http_status(URL, {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
                                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode())
        check("no token -> 401", status == 401, f"HTTP {status}")

        names, err = safe(tools_for, good)
        check("tools/list with valid token", names is not None, err or ", ".join(names or []))
        if names:
            check("names are <target>_<tool>", "fakea_echo" in names and "fakeb_show_hosts" in names)
            check("read-only policy hides add_host", not any(n.endswith("add_host") for n in names))

        res, err = safe(call, good, "fakeb_echo", {"text": "hi"})
        check("tools/call routes to the right target", res and not res[0] and res[1] == "fakeb: hi", err or str(res))

        res, err = safe(call, good, "fakea_add_host", {"name": "evil"})
        check("calling a hidden mutating tool is denied", err or (res and res[0]), err or str(res))

        for label, tok in (("wrong scope", token(key, scope="other/scope")),
                           ("wrong client", token(key, client_id="intruder")),
                           ("id token", token(key, token_use="id")),
                           ("wrong issuer", token(key, issuer="https://evil.example"))):
            names2, err = safe(tools_for, tok)
            check(f"{label} -> no tools", err is not None or not names2, err or f"{len(names2)} tools visible")

        res, err = safe(call, good, "fakea_seen_headers", {},
                        {"MANAGEMENT-HOST": "attacker.example", "API-KEY": "stolen", "X-Probe": "1"})
        seen = (res or (None, ""))[1]
        leaked = [h for h in ("management-host", "api-key", "x-probe", "authorization") if h in seen.split(",")]
        check("client headers are NOT forwarded to backends", res is not None and not leaked,
              err or f"backend saw: {seen}")

        procs["fakeb"].kill()
        procs["fakeb"].wait()
        time.sleep(1)
        names3, err = safe(tools_for, good)
        check("one backend down -> healthy targets still served (failOpen)",
              names3 and any(n.startswith("fakea_") for n in names3), err or ", ".join(names3 or []))
        procs["fakeb"] = start_backend("fakeb")
        wait_http("http://127.0.0.1:8102/mcp")
        res, err = safe(call, good, "fakeb_echo", {"text": "back"})
        check("restarted backend recovers without client action", res and res[1] == "fakeb: back", err or str(res))

        _, metrics = http_status("http://127.0.0.1:15020/metrics")
        mcp_lines = [ln for ln in metrics.splitlines() if "mcp" in ln.lower() and not ln.startswith("#")]
        check("prometheus metrics include MCP series", bool(mcp_lines), (mcp_lines[:3] or ["none"])[0][:160])
        with open(os.path.join(OUT, "metrics.txt"), "w") as fh:
            fh.write(metrics)
    finally:
        gw.terminate()
        for p in procs.values():
            p.terminate()

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
