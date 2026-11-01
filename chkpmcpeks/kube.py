"""kubectl/helm helpers bound to this stack's own kubeconfig (never ~/.kube/config)."""

from __future__ import annotations

import json
import os
import time

from . import tools
from .awsutil import log
from .kube_auth import kubeconfig_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHART = os.path.join(ROOT, "charts", "checkpoint-mcp")
PLATFORM_MANIFEST = os.path.join(ROOT, "deploy", "platform.yaml")

# Pinned add-on charts (bumped deliberately, see docs/runbooks/upgrade.md).
ADDONS = {
    "external-secrets": {
        "repo": "https://charts.external-secrets.io", "chart": "external-secrets", "version": "2.14.0",
        "namespace": "external-secrets",
        "set": ["installCRDs=true", "serviceAccount.name=external-secrets",
                "webhook.port=9443", "log.level=info"],
    },
    "reloader": {
        "repo": "https://stakater.github.io/stakater-charts", "chart": "reloader", "version": "2.2.19",
        "namespace": "reloader",
        "set": ["reloader.watchGlobally=false", "reloader.namespaces={chkp-mcp}",
                "reloader.readOnlyRootFileSystem=true", "reloader.logFormat=json"],
    },
}


class Kube:
    def __init__(self, cluster_name, profile=None):
        self.kubeconfig = kubeconfig_path(cluster_name)
        self.env = {"KUBECONFIG": self.kubeconfig}
        if profile:
            self.env["AWS_PROFILE"] = profile

    # -- kubectl ---------------------------------------------------------------
    def kubectl(self, *args, check=True, capture=True, stream=False):
        return tools.run("kubectl", list(args), env=self.env, check=check, capture=capture and not stream,
                         stream=stream)[1]

    def get_json(self, *args):
        out = self.kubectl("get", *args, "-o", "json", check=False)
        try:
            return json.loads(out or "{}")
        except ValueError:
            return {}

    def apply_file(self, path):
        self.kubectl("apply", "-f", path, capture=False, stream=True)

    def wait_api(self, attempts=60, delay=10):
        for _ in range(attempts):
            rc, _ = tools.run("kubectl", ["get", "--raw", "/readyz"], env=self.env, check=False, capture=True)
            if rc == 0:
                return True
            time.sleep(delay)
        return False

    def wait_crd(self, name, attempts=60, delay=5):
        for _ in range(attempts):
            if self.get_json("crd", name).get("metadata"):
                return True
            time.sleep(delay)
        return False

    # -- helm -----------------------------------------------------------------
    def helm(self, *args, check=True, stream=True):
        return tools.run("helm", list(args), env=self.env, check=check, capture=not stream, stream=stream)[1]

    def install_addon(self, name, timeout="10m"):
        a = ADDONS[name]
        args = ["upgrade", "--install", name, a["chart"], "--repo", a["repo"], "--version", a["version"],
                "--namespace", a["namespace"], "--create-namespace", "--wait", "--timeout", timeout]
        for s in a["set"]:
            args += ["--set", s]
        self.helm(*args)

    def release_exists(self, name, namespace):
        rc, _ = tools.run("helm", ["status", name, "-n", namespace], env=self.env, check=False, capture=True)
        return rc == 0

    def uninstall(self, name, namespace, timeout="10m"):
        if self.release_exists(name, namespace):
            self.helm("uninstall", name, "-n", namespace, "--wait", "--timeout", timeout, check=False)
        else:
            log(f"  helm release {namespace}/{name} not installed")

    # -- workload status ---------------------------------------------------------
    def pods(self, namespace, selector):
        return self.get_json("pods", "-n", namespace, "-l", selector).get("items", [])

    def ingress_hostname(self, namespace, name="checkpoint-mcp"):
        ing = self.get_json("ingress", name, "-n", namespace)
        for lb in (ing.get("status", {}).get("loadBalancer", {}).get("ingress") or []):
            if lb.get("hostname"):
                return lb["hostname"]
        return ""


def pod_ready(pod):
    for c in pod.get("status", {}).get("conditions", []) or []:
        if c.get("type") == "Ready":
            return c.get("status") == "True"
    return False
