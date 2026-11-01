"""Thin wrapper around the two Terraform root modules:

    terraform/build     ECR, CodeBuild, source bucket      (cheap, outlives clusters)
    terraform/platform  VPC, EKS Auto Mode, Cognito, Pod Identity, ACM, add-ons

Each stack keeps its own local state under its directory (gitignored) unless
the operator configures a backend.tf.
"""

from __future__ import annotations

import json
import os

from . import tools
from .awsutil import log

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STACKS = {"build": os.path.join(ROOT, "terraform", "build"),
          "platform": os.path.join(ROOT, "terraform", "platform")}


def _env(profile):
    env = {"TF_IN_AUTOMATION": "1", "TF_INPUT": "0", "CHECKPOINT_DISABLE": "1"}
    if profile:
        env["AWS_PROFILE"] = profile
    return env


def tf_vars(cfg, extra=None):
    out = ["-var", f"region={cfg.region}", "-var", f"prefix={cfg.prefix}"]
    for k, v in (extra or {}).items():
        out += ["-var", f"{k}={json.dumps(v) if isinstance(v, (list, dict)) else v}"]
    return out


def init(stack, profile=None):
    tools.run("terraform", ["init", "-input=false", "-no-color", "-upgrade=false"],
              cwd=STACKS[stack], env=_env(profile), stream=False, capture=True)


def apply(stack, cfg, profile=None, extra_vars=None):
    init(stack, profile)
    tools.run("terraform", ["apply", "-auto-approve", "-input=false", "-no-color", *tf_vars(cfg, extra_vars)],
              cwd=STACKS[stack], env=_env(profile))


def destroy(stack, cfg, profile=None, extra_vars=None):
    if not has_state(stack):
        log(f"  terraform/{stack}: no state -- nothing to destroy")
        return
    init(stack, profile)
    tools.run("terraform", ["destroy", "-auto-approve", "-input=false", "-no-color", *tf_vars(cfg, extra_vars)],
              cwd=STACKS[stack], env=_env(profile))


def outputs(stack, profile=None):
    """{name: value} from `terraform output -json`, or {} when never applied."""
    if not has_state(stack):
        return {}
    _, out = tools.run("terraform", ["output", "-json", "-no-color"], cwd=STACKS[stack],
                       env=_env(profile), capture=True)
    try:
        return {k: v.get("value") for k, v in json.loads(out or "{}").items()}
    except ValueError:
        return {}


def has_state(stack):
    path = os.path.join(STACKS[stack], "terraform.tfstate")
    if os.path.exists(os.path.join(STACKS[stack], "backend.tf")):
        return True  # remote state: let terraform decide
    try:
        with open(path, encoding="utf-8") as fh:
            return bool(json.load(fh).get("resources"))
    except (OSError, ValueError):
        return False
