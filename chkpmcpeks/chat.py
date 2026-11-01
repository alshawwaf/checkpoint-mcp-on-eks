"""`chkpmcpeks chat "question"` -- ask the in-cluster agent, streaming.

Mints a Cognito token, POSTs to <ALB>/v1/chat with stream=true and renders the
server-sent events: tool calls as they happen, the answer as it streams, and a
token/cache line at the end. --port-forward reaches the agent through
`kubectl port-forward` instead of the ALB (handy before DNS/ALB are ready).
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request

from . import tools
from .awsutil import log
from .cli import CHAT_EXAMPLES
from .stack import Stack
from .ui import BOLD, C_A, C_ERR, C_MUTED, C_OK, C_WARN, RESET, c, color_wanted


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _events(resp):
    event, data = None, []
    for raw in resp:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line and data:
            try:
                yield event, json.loads("\n".join(data))
            except ValueError:
                pass
            event, data = None, []


def render(resp):
    """Print the SSE stream; return the final 'done' payload (or None)."""
    streaming, final = False, None
    for kind, ev in _events(resp):
        if kind == "start":
            log(c(C_MUTED, f" {ev.get('label')} · {ev.get('model')} · {ev.get('tools')} tools"
                  + (" · prompt caching on" if ev.get("caching") else "")))
            if ev.get("note"):
                log(" " + c(C_WARN, ev["note"]))
        elif kind == "tool_call":
            if streaming:
                print(flush=True)
                streaming = False
            log(" " + c(C_A, "→ tool") + f"  {ev['name']}  " + c(C_MUTED, json.dumps(ev.get("args", {}))[:120]))
        elif kind == "tool_result":
            glyph = c(C_ERR, "✗ error") if ev.get("error") else c(C_OK, "✓ ok")
            log("        " + glyph + "  " + c(C_MUTED, (ev.get("preview") or "").replace("\n", " ")[:140]))
        elif kind == "text":
            if not streaming:
                print(" " + c(C_A, "assistant") + "  ", end="", flush=True)
                streaming = True
            print(ev.get("delta", ""), end="", flush=True)
        elif kind == "done":
            if streaming:
                print(flush=True)
            final = ev
        elif kind == "error":
            if streaming:
                print(flush=True)
            log(c(C_ERR, f" agent error: {ev.get('error')}"))
    return final


def run(cfg, session, args, profile=None):
    if not args.task:
        print(CHAT_EXAMPLES)
        return 0
    st = Stack(cfg, session, profile)
    if not st.deployed:
        log("nothing deployed -- run: python -m chkpmcpeks deploy")
        return 1
    pf = None
    ctx = None
    if args.port_forward:
        port = _free_port()
        pf = subprocess.Popen([tools.require("kubectl"), "port-forward", "-n", cfg.namespace, "svc/chkp-agent",
                               f"{port}:8080"], env={**__import__("os").environ, **st.kube.env},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        url = f"http://127.0.0.1:{port}/v1/chat"
    else:
        base = st.base_url()
        if not base:
            log("the ALB is not ready yet -- retry shortly, or use --port-forward")
            return 1
        url, ctx = f"{base}/v1/chat", st.ssl_context()

    head = c(BOLD + C_A, "◆ chkpmcpeks chat") if color_wanted() else "chkpmcpeks chat"
    log(f"\n {head}  " + c(C_MUTED, url))
    log(" " + c(C_MUTED, "task: ") + args.task + (RESET if color_wanted() else ""))
    body = json.dumps({"prompt": args.task, "stream": True, **({"model": args.model} if args.model else {})}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "text/event-stream",
        "Authorization": f"Bearer {st.token()}"})
    try:
        with urllib.request.urlopen(req, timeout=600, context=ctx) as resp:
            final = render(resp)
    except urllib.error.HTTPError as e:
        log(c(C_ERR, f" HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"))
        return 1
    except urllib.error.URLError as e:
        log(c(C_ERR, f" could not reach the agent: {e.reason}"))
        return 1
    finally:
        if pf:
            pf.terminate()
    if not final:
        return 1
    u = final.get("usage", {})
    parts = [f"{u.get('in', 0):,} in", f"{u.get('out', 0):,} out", f"{u.get('cache_read', 0):,} cache-read"]
    log(" " + c(C_MUTED, "tokens  " + "  ·  ".join(parts)
                + f"  ·  {final.get('cache_hit_pct', 0)}% of input from cache  ·  {final.get('seconds')}s"))
    log(" " + c(C_OK, "✔ done"))
    return 0
