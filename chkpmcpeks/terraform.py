"""Thin wrapper around the two Terraform root modules:

    terraform/build     ECR, CodeBuild, source bucket      (cheap, outlives clusters)
    terraform/platform  VPC, EKS Auto Mode, Cognito, Pod Identity, ACM, add-ons

Each `--prefix` gets its own Terraform workspace (the default stack uses the
`default` workspace), so parallel stacks never share state. State is local
(gitignored) unless the operator adds a backend.tf.
"""

from __future__ import annotations

import json
import os

from . import tools
from .awsutil import log

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STACKS = {"build": os.path.join(ROOT, "terraform", "build"),
          "platform": os.path.join(ROOT, "terraform", "platform")}


def workspace(prefix):
    return prefix or "default"


def _env(profile):
    env = {"TF_IN_AUTOMATION": "1", "TF_INPUT": "0", "CHECKPOINT_DISABLE": "1"}
    if profile:
        env["AWS_PROFILE"] = profile
    return env


def _settings_path(prefix):
    return os.path.join(ROOT, ".chkpmcpeks", f"stack-{workspace(prefix)}.json")


def stack_settings(prefix=""):
    """Operator choices that must survive re-runs (e.g. domain_name). Gitignored."""
    try:
        with open(_settings_path(prefix), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_stack_settings(prefix, **values):
    doc = stack_settings(prefix)
    doc.update({k: v for k, v in values.items() if v is not None})
    os.makedirs(os.path.dirname(_settings_path(prefix)), exist_ok=True)
    with open(_settings_path(prefix), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    return doc


def tf_vars(cfg, extra=None, stack="platform"):
    out = ["-var", f"region={cfg.region}", "-var", f"prefix={cfg.prefix}"]
    saved = stack_settings(cfg.prefix) if stack == "platform" else {}   # e.g. domain_name
    merged = {**saved, **(extra or {})}
    for k, v in merged.items():
        out += ["-var", f"{k}={json.dumps(v) if isinstance(v, (list, dict)) else v}"]
    return out


def init(stack, prefix="", profile=None):
    d, env = STACKS[stack], _env(profile)
    tools.run("terraform", ["init", "-input=false", "-no-color"], cwd=d, env=env, capture=True)
    tools.run("terraform", ["workspace", "select", "-or-create=true", workspace(prefix)], cwd=d, env=env,
              capture=True)


def apply(stack, cfg, profile=None, extra_vars=None):
    init(stack, cfg.prefix, profile)
    tools.run("terraform", ["apply", "-auto-approve", "-input=false", "-no-color", *tf_vars(cfg, extra_vars, stack)],
              cwd=STACKS[stack], env=_env(profile))


def destroy(stack, cfg, profile=None, extra_vars=None):
    if not has_state(stack, cfg.prefix):
        log(f"  terraform/{stack} ({workspace(cfg.prefix)}): no state -- nothing to destroy")
        return
    init(stack, cfg.prefix, profile)
    tools.run("terraform", ["destroy", "-auto-approve", "-input=false", "-no-color", *tf_vars(cfg, extra_vars, stack)],
              cwd=STACKS[stack], env=_env(profile))


def outputs(stack, profile=None, prefix=""):
    """{name: value} from `terraform output -json`, or {} when never applied."""
    if not has_state(stack, prefix):
        return {}
    d, env = STACKS[stack], {**_env(profile), "TF_WORKSPACE": workspace(prefix)}
    _, out = tools.run("terraform", ["output", "-json", "-no-color"], cwd=d, env=env, capture=True)
    try:
        return {k: v.get("value") for k, v in json.loads(out or "{}").items()}
    except ValueError:
        return {}


def state_path(stack, prefix=""):
    ws = workspace(prefix)
    if ws == "default":
        return os.path.join(STACKS[stack], "terraform.tfstate")
    return os.path.join(STACKS[stack], "terraform.tfstate.d", ws, "terraform.tfstate")


def has_state(stack, prefix=""):
    if os.path.exists(os.path.join(STACKS[stack], "backend.tf")):
        return True  # remote state: let terraform decide
    try:
        with open(state_path(stack, prefix), encoding="utf-8") as fh:
            return bool(json.load(fh).get("resources"))
    except (OSError, ValueError):
        return False
