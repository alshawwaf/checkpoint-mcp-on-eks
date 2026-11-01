"""EKS authentication without the AWS CLI.

`eks_token()` builds the same bearer token `aws eks get-token` does: a
presigned STS GetCallerIdentity URL carrying the `x-k8s-aws-id` header, base64url
encoded with the `k8s-aws-v1.` prefix. `write_kubeconfig()` writes a
stack-specific kubeconfig (never touching ~/.kube/config) whose exec plugin
calls `python -m chkpmcpeks eks-token`, so kubectl, helm and the CLI all
authenticate through boto3's normal credential chain.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import sys

import yaml
from botocore.signers import RequestSigner

TOKEN_PREFIX = "k8s-aws-v1."  # noqa: S105 -- protocol prefix, not a secret
TOKEN_TTL_SECONDS = 60          # presign lifetime (EKS accepts up to 15 min of skew)
EXEC_EXPIRY_MINUTES = 14        # tell kubectl to refresh before EKS rejects it


def eks_token(session, region, cluster_name):
    sts = session.client("sts", region_name=region)
    signer = RequestSigner(sts.meta.service_model.service_id, region, "sts", "v4",
                           session.get_credentials(), sts.meta.events)
    params = {
        "method": "GET",
        "url": f"https://sts.{region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15",
        "body": {},
        "headers": {"x-k8s-aws-id": cluster_name},
        "context": {},
    }
    url = signer.generate_presigned_url(params, region_name=region, expires_in=TOKEN_TTL_SECONDS,
                                        operation_name="")
    return TOKEN_PREFIX + base64.urlsafe_b64encode(url.encode("utf-8")).decode("utf-8").rstrip("=")


def exec_credential(token, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    exp = (now + dt.timedelta(minutes=EXEC_EXPIRY_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "kind": "ExecCredential",
        "apiVersion": "client.authentication.k8s.io/v1beta1",
        "spec": {},
        "status": {"expirationTimestamp": exp, "token": token},
    }


def kubeconfig_path(cluster_name):
    base = os.path.join(os.path.expanduser("~"), ".chkpmcpeks")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"kubeconfig-{cluster_name}")


def build_kubeconfig(cluster_name, endpoint, ca_data, region, profile=None, python=None):
    args = ["-m", "chkpmcpeks", "eks-token", "--cluster", cluster_name, "--region", region]
    if profile:
        args += ["--profile", profile]
    return {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": cluster_name, "cluster": {"server": endpoint,
                                                       "certificate-authority-data": ca_data}}],
        "users": [{"name": cluster_name, "user": {"exec": {
            "apiVersion": "client.authentication.k8s.io/v1beta1",
            "command": python or sys.executable,
            "args": args,
            "interactiveMode": "Never",
            "provideClusterInfo": False,
        }}}],
        "contexts": [{"name": cluster_name, "context": {"cluster": cluster_name, "user": cluster_name}}],
        "current-context": cluster_name,
    }


def write_kubeconfig(session, region, cluster_name, profile=None):
    """Describe the cluster and write its kubeconfig. Returns the file path."""
    eks = session.client("eks", region_name=region)
    c = eks.describe_cluster(name=cluster_name)["cluster"]
    doc = build_kubeconfig(cluster_name, c["endpoint"], c["certificateAuthority"]["data"],
                           region, profile=profile)
    path = kubeconfig_path(cluster_name)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(doc, fh, sort_keys=False)
    return path


def print_exec_credential(session, region, cluster_name):
    print(json.dumps(exec_credential(eks_token(session, region, cluster_name))))
    return 0
