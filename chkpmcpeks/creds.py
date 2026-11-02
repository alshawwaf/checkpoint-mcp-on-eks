"""`chkpmcpeks creds template|apply` -- local credentials file -> Secrets Manager.

Same file format as the AgentCore project (one `[server]` section of
KEY=VALUE lines per server), so an existing chkp-credentials.env works
unchanged. Each section becomes that server's own `chkp/<server>` secret.
An optional `[llm]` section (ANTHROPIC_API_KEY / OPENAI_API_KEY / AZURE_OPENAI_API_KEY) fills
this stack's LLM secret for non-Bedrock providers.

Differences from the AgentCore CLI, by design:
  * a secret is created only when missing and is NEVER deleted by this tool
    (the same secrets may be serving the AgentCore deployment);
  * after writing, External Secrets is told to re-sync right away and
    Reloader restarts exactly the affected server pods.
Values are never printed or logged -- only server and key names.
"""

from __future__ import annotations

import configparser
import io
import json
import os
import time

from . import config
from .awsutil import BotoCoreError, ClientError, err_code, log

DEFAULT_FILE = "chkp-credentials.env"
_HEADER = ("# Check Point credentials for chkpmcpeks -- gitignored, NEVER commit.\n"
           "# One [section] per SERVER; each KEY=VALUE becomes that server's chkp/<server>\n"
           "# Secrets Manager secret (shared with checkpoint-mcp-on-aws-agentcore).\n"
           "# Optional [llm] section: OPENAI_API_KEY / AZURE_OPENAI_API_KEY for non-Bedrock LLMs.\n"
           "# Fill in real values, then:  python -m chkpmcpeks creds apply\n")


def parse(text):
    """INI/.env text -> {section: {KEY: value}} (case-preserving, no interpolation)."""
    p = configparser.ConfigParser(interpolation=None)
    p.optionxform = str
    try:
        p.read_string(text)
    except configparser.MissingSectionHeaderError:
        raise ValueError("each server's credentials need a [server-name] header above its KEY=VALUE lines") from None
    except configparser.Error as e:
        raise ValueError(str(e)) from None
    return {s: dict(p[s]) for s in p.sections()}


def load(path):
    with open(path, encoding="utf-8-sig") as fh:
        raw = fh.read()
    if path.endswith(".json"):
        doc = json.loads(raw)
        return {k: v for k, v in doc.items() if not k.startswith("_")}
    return parse(raw)


def has_placeholder(body):
    return any(str(v).startswith(("PLACEHOLDER", "replace-with", "REPLACE_WITH")) for v in body.values())


def template(cfg, path=None):
    path = path or DEFAULT_FILE
    if os.path.exists(path):
        log(f"{path} already exists -- refusing to overwrite (it may hold real credentials).")
        return 1
    buf = io.StringIO()
    buf.write(_HEADER)
    for s in cfg.servers_with_creds():
        buf.write(f"\n[{s}]\n")
        for k, v in cfg.placeholder_for(s).items():
            buf.write(f"{k}={v}\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(buf.getvalue())
    log(f"wrote {path} with {len(cfg.servers_with_creds())} server section(s). Edit it, then: creds apply")
    return 0


def ensure_placeholders(cfg, session, servers=None):
    """Create a placeholder chkp/<server> secret for every selected server that
    has none. Existing secrets (real or not) are left untouched."""
    sm = session.client("secretsmanager", region_name=cfg.region)
    created = []
    for s in cfg.servers_with_creds(servers):
        name = cfg.secret_name(s)
        try:
            sm.describe_secret(SecretId=name)
            continue
        except ClientError as e:
            if err_code(e) != "ResourceNotFoundException":
                raise
        sm.create_secret(Name=name, SecretString=json.dumps(cfg.placeholder_for(s)),
                         Description=f"Check Point {s} MCP server credentials (placeholder until creds apply)",
                         Tags=cfg.tags_kv() + [{"Key": "chkp:consumers", "Value": "eks"}])
        created.append(s)
    return created


def _put(sm, cfg, name, body):
    payload = json.dumps(body)
    try:
        sm.put_secret_value(SecretId=name, SecretString=payload)
    except ClientError as e:
        code = err_code(e)
        if code == "ResourceNotFoundException":
            sm.create_secret(Name=name, SecretString=payload, Tags=cfg.tags_kv())
        elif code == "InvalidRequestException" and "deletion" in str(e).lower():
            sm.restore_secret(SecretId=name)
            sm.put_secret_value(SecretId=name, SecretString=payload)
        else:
            raise


def apply(cfg, session, path=None, kube=None, llm_secret=None):
    path = path or DEFAULT_FILE
    if not os.path.exists(path):
        log(f"no credentials file at {path}. Create one: python -m chkpmcpeks creds template")
        return 1, []
    try:
        doc = load(path)
    except (OSError, ValueError) as e:
        log(f"could not read {path}: {e}")
        return 1, []
    sm = session.client("secretsmanager", region_name=cfg.region)
    applied = []
    for section, body in doc.items():
        if section == "llm":
            if not llm_secret:
                log("  [llm] present but the platform is not deployed yet -- skipped")
                continue
            current = {}
            try:
                current = json.loads(sm.get_secret_value(SecretId=llm_secret)["SecretString"])
            except (ClientError, BotoCoreError, ValueError):
                pass
            current.update({k: v for k, v in body.items() if v})
            _put(sm, cfg, llm_secret, current)
            log(f"  [llm] -> {llm_secret}  ({sum(1 for v in body.values() if v)} key(s); values not printed)")
            continue
        if section not in config.SERVER_CATALOG or not cfg.server_needs_creds(section):
            log(f"  skipping [{section}]: not a credentialed Check Point server")
            continue
        if not body or has_placeholder(body):
            log(f"  skipping [{section}]: empty or still has placeholder values")
            continue
        _put(sm, cfg, cfg.secret_name(section), body)
        log(f"  [{section}] -> {cfg.secret_name(section)}  ({len(body)} key(s); values not printed)")
        applied.append(section)
    if applied and kube is not None:
        resync(kube, cfg, applied)
    return 0, applied


def resync(kube, cfg, servers):
    """Ask External Secrets to re-read now; Reloader then restarts the pods."""
    stamp = str(int(time.time()))
    for s in servers:
        kube.kubectl("annotate", "externalsecret", f"mcp-{s}", "-n", cfg.namespace,
                     f"force-sync={stamp}", "--overwrite", check=False)
    log(f"  re-sync requested for {len(servers)} server(s); Reloader restarts them when the secret changes")


def run(cfg, session, args, profile=None):
    servers = config.parse_servers(args.servers) or cfg.servers
    from dataclasses import replace

    cfg = replace(cfg, servers=tuple(servers))
    if args.action == "template":
        return template(cfg, args.file)
    from .stack import Stack

    st = Stack(cfg, session, profile)
    kube = st.kube if st.deployed else None
    rc, applied = apply(cfg, session, args.file, kube=kube, llm_secret=st.out.get("llm_secret_name"))
    if rc == 0:
        log(f"applied {len(applied)} server secret(s)" + ("" if kube else " (cluster not deployed yet)"))
    return rc
