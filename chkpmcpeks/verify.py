"""`chkpmcpeks status` -- read-only health and catalog check. Changes nothing.

Reports: cluster + nodes, every MCP server pod, the gateway and the agent, the
public endpoint, then mints a Cognito token and lists the aggregated tool
catalog THROUGH THE ALB, and confirms an unauthenticated request is refused.
"""

from __future__ import annotations

from . import config, mcpclient, ui
from .awsutil import log
from .kube import pod_ready
from .stack import Stack, http_json

STEPS = ["Stack outputs", "Workloads", "Public endpoint", "Auth + tool catalog"]


def check(st, rep=None, verbose=True):
    """Shared by `status` and the tail of `deploy`. Returns (ok, summary_lines)."""
    cfg, kube = st.cfg, st.kube
    lines, ok = [], True

    if rep:
        rep.begin("Workloads")
    nodes = kube.get_json("nodes").get("items", [])
    arch = sorted({n["metadata"]["labels"].get("kubernetes.io/arch", "?") for n in nodes})
    log(f"  nodes: {len(nodes)} ({', '.join(arch) or '-'})")
    for comp, label in (("mcp-server", "app.kubernetes.io/component=mcp-server"),
                        ("gateway", "app.kubernetes.io/name=agentgateway"),
                        ("agent", "app.kubernetes.io/name=chkp-agent")):
        pods = kube.pods(cfg.namespace, label)
        ready = [p for p in pods if pod_ready(p)]
        if comp == "mcp-server":
            for p in sorted(pods, key=lambda x: x["metadata"]["labels"].get("chkp.checkpoint.com/server", "")):
                server = p["metadata"]["labels"].get("chkp.checkpoint.com/server", "?")
                restarts = sum(c.get("restartCount", 0) for c in p.get("status", {}).get("containerStatuses", []))
                log(f"    {'✔' if pod_ready(p) else '✖'} {server:20} {p['status'].get('phase')}"
                    + (f"  restarts={restarts}" if restarts else ""))
        log(f"  {comp}: {len(ready)}/{len(pods)} ready")
        lines.append(f"  {comp:11}: {len(ready)}/{len(pods)} pods ready")
        ok &= bool(pods) and len(ready) == len(pods)

    if rep:
        rep.begin("Public endpoint")
    base = st.base_url()
    ctx = st.ssl_context()
    if not base:
        log("  the ALB has no hostname yet")
        return False, lines + ["  endpoint   : ALB not provisioned yet -- re-run status in a minute"]
    log(f"  {base}  (TLS verified{' against the stack CA' if st.ca_file() else ''})")
    status, _ = http_json(f"{base}/healthz", ctx=ctx)
    log(f"  agent /healthz -> {status}")
    lines.append(f"  MCP URL    : {base}/mcp")
    lines.append(f"  Agent URL  : {base}/v1/chat")
    ok &= status == 200

    if rep:
        rep.begin("Auth + tool catalog")
    status, _ = http_json(f"{base}/mcp", method="POST",
                          body={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, ctx=ctx)
    log(f"  unauthenticated MCP request -> HTTP {status}" + ("  ✔ refused" if status == 401 else "  ✖ expected 401"))
    ok &= status == 401
    try:
        names = mcpclient.list_tools(f"{base}/mcp", st.token(), ctx)
    except BaseException as e:  # noqa: BLE001 -- anyio groups
        log(f"  tools/list failed: {type(e).__name__}: {str(e)[:200]}")
        return False, lines + ["  catalog    : tools/list FAILED (see log)"]
    lines += [""] + mcpclient.summarize(names, config.TOOL_SEPARATOR)
    ok &= bool(names)
    return ok, lines


def run(cfg, session, args, profile=None):
    st = Stack(cfg, session, profile)
    rep = ui.Reporter("status", STEPS, context=f"{cfg.region} · {cfg.cluster_name}")
    rep.begin("Stack outputs")
    if not st.deployed:
        log("  terraform/platform has no state -- nothing deployed. Run: python -m chkpmcpeks deploy")
        rep.close(False, ["  not deployed"])
        return 1
    log(f"  cluster {st.out['cluster_name']} · issuer {st.out['cognito_issuer']}")
    ok, lines = check(st, rep)
    rep.close(ok, lines)
    return 0 if ok else 1
