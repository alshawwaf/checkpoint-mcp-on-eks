"""Inbound JWT validation for the agent API.

Amazon Cognito client-credentials (M2M) access tokens carry `iss`, `client_id`,
`scope` (space-separated), `token_use=access` and `exp` -- and NO `aud`. So the
checks are: RS256 signature against the issuer's JWKS, issuer, expiry,
token_use, an allow-list of client ids, and a required scope. When
AUTH_AUDIENCE is set (Okta, Entra and Keycloak issue `aud`), audience is
enforced as well.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt


class AuthError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


@dataclass
class Principal:
    client_id: str
    scopes: tuple
    claims: dict


class JWTValidator:
    def __init__(self, issuer, jwks_url=None, audience="", allowed_client_ids=(), required_scope="",
                 jwk_client=None, leeway=30):
        if not issuer:
            raise ValueError("AUTH_ISSUER is required unless AUTH_DISABLED=true")
        self.issuer = issuer.rstrip("/")
        self.audience = audience or None
        self.allowed = set(allowed_client_ids)
        self.required_scope = required_scope
        self.leeway = leeway
        self.jwk_client = jwk_client or jwt.PyJWKClient(
            jwks_url or f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600)

    def validate(self, authorization_header):
        if not authorization_header or not authorization_header.lower().startswith("bearer "):
            raise AuthError(401, "missing bearer token")
        token = authorization_header.split(" ", 1)[1].strip()
        try:
            key = self.jwk_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token, key, algorithms=["RS256"], issuer=self.issuer, audience=self.audience,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "iss"], "verify_aud": self.audience is not None},
            )
        except jwt.PyJWTError as e:
            raise AuthError(401, f"invalid token: {type(e).__name__}") from None
        if claims.get("token_use", "access") != "access":
            raise AuthError(401, "not an access token")
        client_id = claims.get("client_id") or claims.get("azp") or claims.get("sub") or ""
        if self.allowed and client_id not in self.allowed:
            raise AuthError(403, "client not allowed")
        scopes = tuple(str(claims.get("scope", "")).split()) or tuple(claims.get("scp", []) or ())
        if self.required_scope and self.required_scope not in scopes:
            raise AuthError(403, f"missing scope {self.required_scope}")
        return Principal(client_id=client_id, scopes=scopes, claims=claims)
