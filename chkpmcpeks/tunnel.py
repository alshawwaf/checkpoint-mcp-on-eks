"""Reach the cluster's Kubernetes API, privately by default.

The EKS API endpoint is private unless the operator opts into a public one.
`connect()` decides how this machine reaches it and writes the stack's
kubeconfig accordingly:

  * public endpoint enabled AND this machine's IP is in its allow-list
    -> talk to it directly (classic kubeconfig);
  * otherwise -> open an AWS Systems Manager port-forward through the
    stack's API access host (no inbound ports, no SSH) to the private
    endpoint, and point the kubeconfig at the local end. TLS is still
    verified against the real endpoint name (`tls-server-name`), and kubectl
    still authenticates with the caller's own IAM identity.

The tunnel is a child `session-manager-plugin` process that lives as long as
this CLI process and is closed at exit. No AWS CLI is needed: the session is
started with boto3 and handed to the plugin the same way the AWS CLI does.
"""

from __future__ import annotations

import atexit
import ipaddress
import json
import socket
import subprocess
import time
import urllib.request
from urllib.parse import urlparse

import yaml

from . import tools
from .awsutil import log
from .kube_auth import build_kubeconfig, kubeconfig_path

DOCUMENT = "AWS-StartPortForwardingSessionToRemoteHost"
_active: dict[str, dict] = {}


def public_ip(timeout=5):
    """This machine's public IPv4 as seen by AWS (checkip.amazonaws.com), or ''."""
    try:
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=timeout) as r:  # noqa: S310
            ip = r.read().decode().strip()
        ipaddress.IPv4Address(ip)
        return ip
    except (OSError, ValueError):
        return ""


def ip_allowed(ip, cidrs):
    if not ip:
        return False
    addr = ipaddress.ip_address(ip)
    return any(addr in ipaddress.ip_network(c, strict=False) for c in cidrs or [])


def choose_route(vpc_config, my_ip):
    """'direct' when the public endpoint is on and lets this IP in, else 'tunnel'. Pure; tested."""
    if vpc_config.get("endpointPublicAccess") and ip_allowed(my_ip, vpc_config.get("publicAccessCidrs")):
        return "direct"
    return "tunnel"


def tunnel_kubeconfig(doc, local_port, endpoint):
    """Point a kubeconfig at the local end of the tunnel, still verifying the real name."""
    host = urlparse(endpoint).hostname
    cluster = doc["clusters"][0]["cluster"]
    cluster["server"] = f"https://127.0.0.1:{local_port}"
    cluster["tls-server-name"] = host
    return doc


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_open(port, timeout=1.0):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_ssm_online(ssm, instance_id, minutes=6):
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        info = ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]).get("InstanceInformationList", [])
        if info and info[0].get("PingStatus") == "Online":
            return True
        time.sleep(10)
    return False


def open_tunnel(session, region, instance_id, endpoint, profile=None):
    """Start an SSM port-forward to the private endpoint. Returns the local port."""
    plugin = tools.require("session-manager-plugin")
    host = urlparse(endpoint).hostname
    ssm = session.client("ssm", region_name=region)
    if not wait_ssm_online(ssm, instance_id):
        raise RuntimeError(f"the API access host {instance_id} is not registered with Systems Manager yet")
    port = _free_port()
    params = {"host": [host], "portNumber": ["443"], "localPortNumber": [str(port)]}
    resp = ssm.start_session(Target=instance_id, DocumentName=DOCUMENT, Parameters=params)
    request = {"Target": instance_id, "DocumentName": DOCUMENT, "Parameters": params}
    proc = subprocess.Popen(  # noqa: S603 -- fixed argv, no shell
        [plugin, json.dumps({k: resp[k] for k in ("SessionId", "TokenValue", "StreamUrl")}), region,
         "StartSession", profile or "", json.dumps(request), f"https://ssm.{region}.amazonaws.com"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            ssm.terminate_session(SessionId=resp["SessionId"])
        except Exception:  # noqa: BLE001,S110 -- best effort at exit
            pass

    atexit.register(close)
    for _ in range(60):
        if proc.poll() is not None:
            raise RuntimeError("session-manager-plugin exited before the tunnel opened")
        if _port_open(port):
            return port, close
        time.sleep(0.5)
    close()
    raise RuntimeError("the SSM tunnel to the Kubernetes API did not open within 30 seconds")


def connect(session, region, cluster_name, profile=None, access_instance_id="", quiet=False):
    """Write the stack's kubeconfig so kubectl/helm reach the API. Returns its path."""
    if cluster_name in _active:
        return _active[cluster_name]["path"]
    eks = session.client("eks", region_name=region)
    c = eks.describe_cluster(name=cluster_name)["cluster"]
    doc = build_kubeconfig(cluster_name, c["endpoint"], c["certificateAuthority"]["data"], region, profile=profile)
    route = choose_route(c.get("resourcesVpcConfig", {}), public_ip())
    if route == "tunnel":
        if not access_instance_id:
            raise RuntimeError("the Kubernetes API is private and this stack has no API access host: "
                               "run from inside the VPC, or enable enable_api_access_host")
        port, close = open_tunnel(session, region, access_instance_id, c["endpoint"], profile)
        doc = tunnel_kubeconfig(doc, port, c["endpoint"])
        if not quiet:
            log(f"  Kubernetes API: private endpoint, via SSM tunnel through {access_instance_id} (127.0.0.1:{port})")
    elif not quiet:
        log("  Kubernetes API: public endpoint (this IP is on its allow-list)")
    path = kubeconfig_path(cluster_name)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(doc, fh, sort_keys=False)
    _active[cluster_name] = {"path": path, "route": route}
    return path
