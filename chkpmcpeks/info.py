"""`chkpmcpeks endpoints` and `chkpmcpeks token` -- what an external tool needs.

    python -m chkpmcpeks endpoints                    # human-readable
    python -m chkpmcpeks endpoints --format sh        # export CHKP_*=... (bash/zsh)
    python -m chkpmcpeks endpoints --format ps1       # $env:CHKP_*=...  (PowerShell)
    python -m chkpmcpeks endpoints --reveal-secret    # include the client secret
    python -m chkpmcpeks endpoints --copy-secret      # client secret -> clipboard, never printed
    python -m chkpmcpeks token                        # a fresh bearer token, nothing else

The client secret is printed only with --reveal-secret, so it never lands in a
terminal or log by accident. Tokens last 60 minutes.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from .awsutil import log
from .stack import Stack


def copy_to_clipboard(text):
    """Put text on the clipboard without echoing it. Returns the tool used, or ''."""
    candidates = [["clip"]] if sys.platform.startswith("win") else (
        [["pbcopy"]] if sys.platform == "darwin" else [["wl-copy"], ["xclip", "-selection", "clipboard"]])
    for cmd in candidates:
        if shutil.which(cmd[0]):
            subprocess.run(cmd, input=text.encode("utf-8"), check=True)
            return cmd[0]
    return ""


def collect(st, reveal=False):
    out = st.out
    base = st.base_url()
    info = {
        "CHKP_BASE_URL": base,
        "CHKP_MCP_URL": f"{base}/mcp" if base else "",
        "CHKP_AGENT_URL": f"{base}/v1/chat" if base else "",
        "CHKP_TOKEN_URL": out["cognito_token_url"],
        "CHKP_CLIENT_ID": out["external_client_id"],
        "CHKP_SCOPE": out["cognito_scope"],
        "CHKP_CA_FILE": st.ca_file(),
    }
    if reveal:
        info["CHKP_CLIENT_SECRET"] = st.client_secret()
    return info


def run(cfg, session, args, profile=None):
    st = Stack(cfg, session, profile)
    if not st.deployed:
        log("nothing deployed -- run: python -m chkpmcpeks deploy")
        return 1
    if args.cmd == "token":
        print(st.token())
        return 0
    if getattr(args, "copy_secret", False):
        tool = copy_to_clipboard(st.client_secret())
        log(f"client secret copied to the clipboard ({tool})" if tool else "no clipboard tool found (clip/pbcopy/xclip)")
        return 0 if tool else 1
    info = collect(st, reveal=args.reveal_secret)
    for k, v in info.items():
        if args.format == "sh":
            print(f"export {k}='{v}'")
        elif args.format == "ps1":
            print(f"$env:{k}='{v}'")
        else:
            print(f"{k:20} {v}")
    if not args.reveal_secret and args.format == "text":
        log("\n(client secret hidden -- add --reveal-secret to print it for a tool's credential store)")
    return 0
