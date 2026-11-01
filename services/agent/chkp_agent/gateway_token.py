"""Client-credentials token for the agent's own calls to the MCP gateway.

Cached until 60 s before expiry: every Cognito M2M token request is billed, so
minting a token per chat request would cost money for nothing.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.parse
import urllib.request


class TokenProvider:
    def __init__(self, token_url, client_id, client_secret, scope, opener=None):
        self.token_url, self.client_id, self.client_secret, self.scope = (
            token_url, client_id, client_secret, scope)
        self._token, self._exp = "", 0.0
        self._lock = threading.Lock()
        self._open = opener or urllib.request.urlopen

    @property
    def enabled(self):
        return bool(self.token_url and self.client_id and self.client_secret)

    def get(self):
        if not self.enabled:
            return ""
        with self._lock:
            if self._token and time.time() < self._exp - 60:
                return self._token
            basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            body = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": self.scope}).encode()
            req = urllib.request.Request(self.token_url, data=body, method="POST", headers={
                "Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}"})
            with self._open(req, timeout=15) as resp:
                doc = json.loads(resp.read().decode())
            self._token = doc["access_token"]
            self._exp = time.time() + int(doc.get("expires_in", 3600))
            return self._token
