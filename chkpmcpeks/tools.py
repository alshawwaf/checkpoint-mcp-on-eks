"""Locate and run the external tools the CLI drives (terraform, helm, kubectl, session-manager-plugin).

Windows machines often carry an old binary earlier on PATH (for example a
32-bit Terraform in Program Files) alongside a current one installed through
scoop/winget. Rather than make the user edit PATH, `find_tool` scans EVERY
PATH entry (plus well-known package-manager shim folders), asks each candidate
for its version, and returns the newest one that meets the minimum.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

from .awsutil import log

# (minimum version, version args, install hints)
TOOLS = {
    "terraform": ((1, 10, 0), ["version", "-json"], {
        "windows": "scoop install terraform", "darwin": "brew install hashicorp/tap/terraform",
        "linux": "https://developer.hashicorp.com/terraform/install"}),
    "helm": ((3, 14, 0), ["version", "--short"], {
        "windows": "scoop install helm", "darwin": "brew install helm",
        "linux": "https://helm.sh/docs/intro/install/"}),
    "kubectl": ((1, 30, 0), ["version", "--client", "-o", "json"], {
        "windows": "scoop install kubectl", "darwin": "brew install kubectl",
        "linux": "https://kubernetes.io/docs/tasks/tools/"}),
    # Opens the SSM port-forward to the private Kubernetes API endpoint.
    "session-manager-plugin": ((1, 2, 0), ["--version"], {
        "windows": "scoop bucket add extras; scoop install aws-session-manager-plugin",
        "darwin": "brew install --cask session-manager-plugin",
        "linux": "https://docs.aws.amazon.com/systems-manager/latest/userguide/install-plugin-debian-and-ubuntu.html"}),
}

_VERSION_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
_cache: dict[str, tuple[str, tuple] | None] = {}


def platform_key():
    if sys.platform.startswith("win"):
        return "windows"
    return "darwin" if sys.platform == "darwin" else "linux"


def parse_version(text):
    """First semver-looking triple in `text`, as a tuple of ints (or None)."""
    m = _VERSION_RE.search(text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def _candidate_dirs():
    seen = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if d and d not in seen:
            seen.append(d)
    home = os.path.expanduser("~")
    for extra in (os.path.join(home, "scoop", "shims"), "/opt/homebrew/bin", "/usr/local/bin"):
        if os.path.isdir(extra) and extra not in seen:
            seen.append(extra)
    return seen


def _candidates(name):
    exts = [".exe", ".cmd", ".bat", ""] if platform_key() == "windows" else [""]
    out = []
    for d in _candidate_dirs():
        for ext in exts:
            p = os.path.join(d, name + ext)
            if os.path.isfile(p) and os.access(p, os.X_OK) and p not in out:
                out.append(p)
    return out


def _probe_version(path, args):
    try:
        res = subprocess.run([path, *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_version(res.stdout + res.stderr)


def find_tool(name):
    """(path, version) of the newest `name` meeting the minimum, else None."""
    if name in _cache:
        return _cache[name]
    minimum, args, _ = TOOLS[name]
    best = None
    for path in _candidates(name):
        ver = _probe_version(path, args)
        if ver and ver >= minimum and (best is None or ver > best[1]):
            best = (path, ver)
    _cache[name] = best
    return best


def describe_tool(name):
    """Human line for doctor: found/too old/missing, with an install hint."""
    minimum, args, hints = TOOLS[name]
    found = find_tool(name)
    need = ".".join(map(str, minimum))
    if found:
        return True, f"{name} {'.'.join(map(str, found[1]))}  ({found[0]})"
    old = [(p, _probe_version(p, args)) for p in _candidates(name)]
    old = [(p, v) for p, v in old if v]
    hint = hints.get(platform_key(), "")
    if old:
        p, v = max(old, key=lambda pv: pv[1])
        return False, f"{name} {'.'.join(map(str, v))} at {p} is older than {need} -- install: {hint}"
    return False, f"{name} not found (need >= {need}) -- install: {hint}"


def require(name):
    found = find_tool(name)
    if not found:
        ok, line = describe_tool(name)
        log(line)
        raise SystemExit(1)
    return found[0]


def run(name, args, cwd=None, env=None, check=True, capture=False, stream=True, timeout=None):
    """Run a tool. Streams output line by line through log() unless capture.
    Returns (returncode, stdout_text)."""
    exe = require(name) if name in TOOLS else (shutil.which(name) or name)
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    if capture or not stream:
        res = subprocess.run([exe, *args], cwd=cwd, env=full_env, capture_output=True,
                             text=True, timeout=timeout)
        if check and res.returncode != 0:
            log((res.stdout or "") + (res.stderr or ""))
            raise RuntimeError(f"{name} {' '.join(args[:2])} failed (exit {res.returncode})")
        return res.returncode, res.stdout
    proc = subprocess.Popen([exe, *args], cwd=cwd, env=full_env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    lines = []
    for line in proc.stdout:
        line = line.rstrip("\n")
        lines.append(line)
        log("  " + line)
    rc = proc.wait(timeout=timeout)
    if check and rc != 0:
        raise RuntimeError(f"{name} {' '.join(args[:2])} failed (exit {rc})")
    return rc, "\n".join(lines)
