"""Everything a client-side command needs to talk to a deployed stack:
Terraform outputs, the public URL, the CA to trust, and a Cognito token.

Tokens are minted with the `external-clients` app client (its secret is read
from Cognito, never stored or printed) and cached in memory only.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from . import terraform
from .awsutil import log, tls_context
from .kube import Kube


class Stack:
    def __init__(self, cfg, session, profile=None):
        self.cfg, self.session, self.profile = cfg, session, profile
        self.out = terraform.outputs("platform", profile)
        self._token, self._exp = "", 0.0

    @property
    def deployed(self):
        return bool(self.out.get("cluster_name"))

    @property
    def kube(self):
        return Kube(self.out.get("cluster_name") or self.cfg.cluster_name, self.profile)

    # -- TLS -------------------------------------------------------------------
    def ca_file(self):
        """Path of the self-signed ALB certificate to trust ('' with a real domain)."""
        pem = self.out.get("self_signed_cert_pem") or ""
        if not pem:
            return ""
        path = os.path.join(os.path.expanduser("~"), ".chkpmcpeks", f"{self.out['cluster_name']}-alb-ca.pem")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(pem)
        return path

    def ssl_context(self):
        return tls_context(self.ca_file() or None)

    # -- URLs ------------------------------------------------------------------
    def base_url(self):
        host = self.out.get("domain_name") or self.kube.ingress_hostname(self.cfg.namespace)
        return f"https://{host}" if host else ""

    # -- tokens ----------------------------------------------------------------
    def client_secret(self):
        cog = self.session.client("cognito-idp", region_name=self.cfg.region)
        desc = cog.describe_user_pool_client(UserPoolId=self.out["cognito_user_pool_id"],
                                             ClientId=self.out["external_client_id"])
        return desc["UserPoolClient"]["ClientSecret"]

    def token(self, attempts=12, delay=10):
        if self._token and time.time() < self._exp - 60:
            return self._token
        cid, secret = self.out["external_client_id"], self.client_secret()
        body = urllib.parse.urlencode({"grant_type": "client_credentials",
                                       "scope": self.out["cognito_scope"]}).encode()
        basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        last = ""
        for i in range(attempts):
            req = urllib.request.Request(self.out["cognito_token_url"], data=body, method="POST", headers={
                "Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}"})
            try:
                with urllib.request.urlopen(req, timeout=20, context=tls_context()) as r:
                    doc = json.loads(r.read().decode())
                self._token, self._exp = doc["access_token"], time.time() + int(doc.get("expires_in", 3600))
                return self._token
            except (urllib.error.URLError, ValueError, KeyError) as e:
                last = str(e)
                if i < attempts - 1:
                    time.sleep(delay)   # a brand-new Cognito domain takes a minute to resolve
        raise RuntimeError(f"could not mint a Cognito token: {last}")


def http_json(url, method="GET", body=None, token=None, ctx=None, timeout=30):
    """(status, parsed-or-text) with TLS verification on."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx or ssl.create_default_context()) as r:
            raw = r.read().decode()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read().decode(errors="replace"), e.code
    except urllib.error.URLError as e:
        return None, str(e.reason)
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


def wait_https(url, ctx, attempts=60, delay=10, label=""):
    for i in range(attempts):
        status, _ = http_json(url, ctx=ctx, timeout=10)
        if status == 200:
            return True
        if i and i % 6 == 0:
            log(f"    still waiting for {label or url} (last: {status})")
        time.sleep(delay)
    return False
