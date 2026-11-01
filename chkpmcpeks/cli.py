"""chkpmcpeks -- Check Point MCP servers + a security-ops agent on Amazon EKS.

    python -m chkpmcpeks doctor                       # local read-only preflight
    python -m chkpmcpeks deploy [--servers "..."]     # terraform -> build -> helm -> verify
    python -m chkpmcpeks build                        # container images on CodeBuild -> ECR
    python -m chkpmcpeks status                       # tools/list through the gateway
    python -m chkpmcpeks chat "question"              # ask the agent
    python -m chkpmcpeks creds template|apply         # chkp-credentials.env -> chkp/<server>
    python -m chkpmcpeks endpoints [--format sh|ps1]  # URLs/client id for curl, Postman, n8n, MCP clients
    python -m chkpmcpeks token                        # a fresh bearer token
    python -m chkpmcpeks kubeconfig                   # write a kubeconfig for this stack
    python -m chkpmcpeks destroy [--yes]              # remove everything this stack created

Global options (before or after the subcommand): --region, --prefix, --profile, --plain.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys

from . import __version__, ui
from .awsutil import log, make_session
from .config import DEFAULT_REGION, StackConfig, load_env_file, parse_servers

CHAT_EXAMPLES = """\
example questions (the agent picks the tools):
  chkpmcpeks chat "what is the reputation of the URL https://example.com?"
  chkpmcpeks chat "is the file hash 44d88612fea8a8f36de82e1278abb02f known to be malicious?"
  chkpmcpeks chat "how many hosts are configured, and what access layers exist?"
  chkpmcpeks chat "how do I configure HTTPS inspection on a Quantum gateway?"
"""


def _common():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--region", default=argparse.SUPPRESS, help=f"AWS region (default {DEFAULT_REGION})")
    p.add_argument("--prefix", default=argparse.SUPPRESS, help="namespace a second stack in one account")
    p.add_argument("--profile", default=argparse.SUPPRESS, help="named AWS profile (same as AWS_PROFILE)")
    p.add_argument("--plain", action="store_true", default=argparse.SUPPRESS, help="no colour")
    return p


def build_parser():
    common = _common()
    parser = argparse.ArgumentParser(prog="chkpmcpeks", parents=[common],
                                     description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"chkpmcpeks {__version__}")
    sub = parser.add_subparsers(dest="cmd", metavar="command")

    d = sub.add_parser("doctor", parents=[common], help="local read-only preflight")
    d.add_argument("--no-model-probe", action="store_true", help="skip the Bedrock model probe")

    dep = sub.add_parser("deploy", parents=[common], help="deploy the whole stack (idempotent)")
    dep.add_argument("--servers", default=os.environ.get("SERVERS", ""),
                     help="space/comma list or 'all' (default: the 9 default servers)")
    dep.add_argument("--creds", nargs="?", const="chkp-credentials.env", default=None,
                     help="apply a chkp-credentials.env before the servers start")
    dep.add_argument("--skip-build", action="store_true", help="reuse the images already in ECR")
    dep.add_argument("--domain", default=None,
                     help="public DNS name for the ALB (publicly trusted ACM cert); 'none' to go back to self-signed")
    dep.add_argument("--yes", action="store_true", help="do not ask before creating billable resources")

    b = sub.add_parser("build", parents=[common], help="build images on CodeBuild into ECR")
    b.add_argument("--servers", default=os.environ.get("SERVERS", ""))
    b.add_argument("--only", choices=["servers", "agent"], default=None)

    sub.add_parser("status", parents=[common], help="list the tool catalog through the gateway")

    ch = sub.add_parser("chat", parents=[common], help="ask the security-ops agent",
                        epilog=CHAT_EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    ch.add_argument("task", nargs="?", default="")
    ch.add_argument("--model", default=None, help="force a model id (provider-specific)")
    ch.add_argument("--port-forward", action="store_true",
                    help="reach the agent through kubectl port-forward instead of the ALB")

    cr = sub.add_parser("creds", parents=[common], help="manage Check Point credentials")
    cr.add_argument("action", choices=["template", "apply"])
    cr.add_argument("--file", default=None, help="creds file (default chkp-credentials.env)")
    cr.add_argument("--servers", default=os.environ.get("SERVERS", ""))

    e = sub.add_parser("endpoints", parents=[common], help="URLs, client id and CA for external tools")
    e.add_argument("--format", choices=["text", "sh", "ps1"], default="text")
    e.add_argument("--reveal-secret", action="store_true", help="also print the Cognito client secret")
    sub.add_parser("token", parents=[common], help="print a fresh bearer token (60 min)")

    sub.add_parser("kubeconfig", parents=[common], help="write a kubeconfig for this stack's cluster")

    t = sub.add_parser("eks-token", parents=[common], help=argparse.SUPPRESS)
    t.add_argument("--cluster", required=True)

    x = sub.add_parser("destroy", parents=[common], help="tear down everything this stack created")
    x.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    x.add_argument("--keep-images", action="store_true", help="keep the ECR repositories")
    return parser


def _cfg(args):
    servers = parse_servers(getattr(args, "servers", "") or "")
    from .config import DEFAULT_SERVERS

    cfg = StackConfig(region=getattr(args, "region", None) or os.environ.get("AWS_REGION") or DEFAULT_REGION,
                      prefix=getattr(args, "prefix", "") or "",
                      servers=servers or DEFAULT_SERVERS)
    cfg.validate()
    return cfg


def main(argv=None):
    try:
        return _main(argv)
    except KeyboardInterrupt:
        log("\ninterrupted -- every command is idempotent; re-run to continue.")
        return 130
    except ValueError as e:
        log(f"error: {e}")
        return 2


def _utf8_stdio():
    """Windows consoles default to a legacy code page; the UI uses ✔/▲/◆."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _main(argv=None):
    _utf8_stdio()
    load_env_file()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "plain", False) or os.environ.get("CI"):
        ui.FORCE_PLAIN = True
    if not args.cmd:
        parser.print_help()
        return 0
    cfg = _cfg(args)
    profile = getattr(args, "profile", None) or None
    session = make_session(cfg.region, profile)

    if args.cmd == "eks-token":
        from .kube_auth import print_exec_credential

        return print_exec_credential(session, cfg.region, args.cluster)
    if args.cmd == "doctor":
        from . import doctor

        return doctor.run(cfg, session, probe_models=not args.no_model_probe)
    if args.cmd == "kubeconfig":
        from .kube_auth import write_kubeconfig

        path = write_kubeconfig(session, cfg.region, cfg.cluster_name, profile=profile)
        log(f"wrote {path}")
        log("use it with:  set KUBECONFIG to that path (PowerShell: $env:KUBECONFIG=\"" + path + "\")")
        return 0

    # Commands implemented in their own modules (added phase by phase).
    module = {"deploy": "deploy", "build": "build", "status": "verify", "chat": "chat",
              "creds": "creds", "destroy": "destroy", "endpoints": "info", "token": "info"}[args.cmd]
    try:
        mod = importlib.import_module(f"chkpmcpeks.{module}")
    except ModuleNotFoundError:
        log(f"`{args.cmd}` is not implemented yet in this build.")
        return 1
    return mod.run(cfg, session, args, profile=profile)


if __name__ == "__main__":
    sys.exit(main())
