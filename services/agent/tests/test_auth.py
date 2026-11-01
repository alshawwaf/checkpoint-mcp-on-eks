import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from chkp_agent.auth import AuthError, JWTValidator

ISS = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TEST"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJWK:
    def __init__(self, key):
        self.key = key


class FakeJWKClient:
    def get_signing_key_from_jwt(self, _token):
        return FakeJWK(KEY.public_key())


def tok(key=KEY, **over):
    now = int(time.time())
    claims = {"iss": ISS, "client_id": "good", "sub": "good", "scope": "chkp-mcp/invoke other/x",
              "token_use": "access", "iat": now, "exp": now + 300}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return "Bearer " + jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k"})


def validator(**kw):
    args = dict(issuer=ISS, allowed_client_ids=("good",), required_scope="chkp-mcp/invoke",
                jwk_client=FakeJWKClient())
    args.update(kw)
    return JWTValidator(**args)


def test_valid_cognito_m2m_token_without_aud():
    p = validator().validate(tok())
    assert p.client_id == "good"
    assert "chkp-mcp/invoke" in p.scopes


@pytest.mark.parametrize("header,status", [
    ("", 401),
    ("Basic abc", 401),
    (tok(client_id="intruder", sub="intruder"), 403),
    (tok(scope="other/x"), 403),
    (tok(token_use="id"), 401),
    (tok(iss="https://evil.example"), 401),
    (tok(exp=int(time.time()) - 3600), 401),
    (tok(key=OTHER), 401),
])
def test_rejections(header, status):
    with pytest.raises(AuthError) as e:
        validator().validate(header)
    assert e.value.status == status


def test_audience_enforced_when_configured():
    v = validator(audience="api://chkp")
    with pytest.raises(AuthError):
        v.validate(tok())
    assert v.validate(tok(aud="api://chkp")).client_id == "good"


def test_issuer_required():
    with pytest.raises(ValueError):
        JWTValidator(issuer="", jwk_client=FakeJWKClient())
