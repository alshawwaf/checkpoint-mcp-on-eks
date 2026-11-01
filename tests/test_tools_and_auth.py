import base64
import datetime as dt

import boto3

from chkpmcpeks import kube_auth, tools


def test_parse_version():
    assert tools.parse_version("Terraform v1.17.1\non windows_amd64") == (1, 17, 1)
    assert tools.parse_version('{"terraform_version":"1.10.0"}') == (1, 10, 0)
    assert tools.parse_version("v4.3.1+g123") == (4, 3, 1)
    assert tools.parse_version("nothing") is None


def test_eks_token_shape():
    session = boto3.Session(aws_access_key_id="AKIDEXAMPLE", aws_secret_access_key="secret",  # noqa: S106
                            region_name="us-east-1")
    token = kube_auth.eks_token(session, "us-east-1", "my-cluster")
    assert token.startswith("k8s-aws-v1.")
    raw = token[len("k8s-aws-v1."):]
    url = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
    assert url.startswith("https://sts.us-east-1.amazonaws.com/?Action=GetCallerIdentity")
    assert "x-k8s-aws-id" in url.lower()


def test_exec_credential_and_kubeconfig():
    now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    cred = kube_auth.exec_credential("tok", now=now)
    assert cred["status"] == {"expirationTimestamp": "2026-01-01T00:14:00Z", "token": "tok"}
    kc = kube_auth.build_kubeconfig("c1", "https://x", "Q0E=", "us-east-1", profile="p", python="py")
    exec_ = kc["users"][0]["user"]["exec"]
    assert exec_["command"] == "py"
    assert exec_["args"][-2:] == ["--profile", "p"]
    assert kc["current-context"] == "c1"
