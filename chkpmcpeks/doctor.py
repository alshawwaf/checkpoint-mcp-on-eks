"""`chkpmcpeks doctor` -- local, read-only preflight. Creates nothing.

Checks: Python and package versions, the external tools (terraform, helm,
kubectl -- newest on PATH wins), AWS identity/region, Bedrock model access
(which models this account can invoke right now), and the `chkp/<server>`
secrets this stack will reuse.
"""

from __future__ import annotations

import sys

from . import tools
from .awsutil import BotoCoreError, ClientError, caller_identity, log, paginate
from .ui import C_ERR, C_MUTED, C_OK, C_WARN, c

PROBE_MODELS = (
    "us.anthropic.claude-sonnet-4-6",
    "us.amazon.nova-2-lite-v1:0",
    "us.amazon.nova-lite-v1:0",
)


def _line(ok, text, warn=False):
    glyph = c(C_OK, "✔") if ok else (c(C_WARN, "▲") if warn else c(C_ERR, "✖"))
    log(f"  {glyph} {text}")


def _pkg_version(mod):
    try:
        from importlib.metadata import version

        return version(mod)
    except Exception:
        return None


def run(cfg, session, probe_models=True):
    failures = 0
    log(c(C_MUTED, "local"))
    py_ok = sys.version_info >= (3, 10)
    _line(py_ok, f"python {sys.version.split()[0]}" + ("" if py_ok else "  (need >= 3.10)"))
    failures += not py_ok
    for mod, need in (("boto3", True), ("PyYAML", True), ("mcp", False)):
        v = _pkg_version(mod)
        _line(bool(v), f"{mod} {v or 'not installed'}" + ("" if v or need else
              "  (needed for status/chat: pip install 'mcp>=2.3,<3')"), warn=not need)
        failures += need and not v
    for name in ("terraform", "helm", "kubectl"):
        ok, text = tools.describe_tool(name)
        _line(ok, text)
        failures += not ok

    log(c(C_MUTED, "aws"))
    ident = caller_identity(session, cfg.region)
    _line(True, f"identity {ident['Arn']}  (account {ident['Account']}, region {cfg.region})")

    sm = session.client("secretsmanager", region_name=cfg.region)
    existing = set()
    try:
        for s in paginate(sm.list_secrets, Filters=[{"Key": "name", "Values": ["chkp/"]}]):
            existing.add(s["Name"])
    except (ClientError, BotoCoreError):
        pass
    have = [s for s in cfg.servers_with_creds() if cfg.secret_name(s) in existing]
    missing = [s for s in cfg.servers_with_creds() if cfg.secret_name(s) not in existing]
    _line(True, f"{len(have)} of {len(cfg.servers_with_creds())} chkp/<server> secrets exist"
          + (f"; deploy writes placeholders for: {', '.join(missing)}" if missing else " (will be reused)"),
          warn=bool(missing))

    if probe_models:
        br = session.client("bedrock-runtime", region_name=cfg.region)
        callable_models = []
        for mid in PROBE_MODELS:
            try:
                br.converse(modelId=mid, messages=[{"role": "user", "content": [{"text": "hi"}]}],
                            inferenceConfig={"maxTokens": 4})
                callable_models.append(mid)
            except (ClientError, BotoCoreError) as e:
                msg = str(e).lower()
                if "anthropic" in mid and ("use case" in msg or "not been submitted" in msg):
                    _line(False, f"{mid}: Anthropic use-case form not submitted (agent falls back to Nova)",
                          warn=True)
        _line(bool(callable_models), "bedrock models callable: " + (", ".join(callable_models) or "none"),
              warn=not callable_models)

    log("")
    if failures:
        log(c(C_ERR, f"doctor: {failures} problem(s) above -- fix them before `deploy`."))
        return 1
    log(c(C_OK, "doctor: ready to deploy."))
    return 0
