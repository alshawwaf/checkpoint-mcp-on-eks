"""Shared AWS plumbing: sessions, identity, error helpers, pagination, waiters,
and the TLS context for stdlib HTTPS calls (ported from the AgentCore
reference project's awsutil.py, trimmed to what the EKS stack needs)."""

from __future__ import annotations

import os
import ssl
import sys
import time

try:
    import boto3
    from botocore.exceptions import (  # noqa: F401  (re-exported)
        BotoCoreError,
        ClientError,
        NoCredentialsError,
        ProfileNotFound,
    )
except ImportError:  # pragma: no cover
    sys.stderr.write("FATAL: boto3 is required.  pip install boto3\n")
    sys.exit(1)

_LOG_SINK = None
_warned_root = False
_TLS_CONTEXT = None


def set_log_sink(fn):
    global _LOG_SINK
    _LOG_SINK = fn


def log(msg=""):
    if _LOG_SINK is not None:
        _LOG_SINK(msg)
    else:
        print(msg, flush=True)


def err_code(exc):
    try:
        return exc.response["Error"]["Code"]
    except Exception:
        return ""


def paginate(fn, **kwargs):
    """Yield every item of a paginated list_* call (auto-detects the list key
    and nextToken/NextToken/NextMarker). Client errors end the iteration."""
    token_key, token_val = None, None
    while True:
        kw = dict(kwargs)
        if token_val:
            kw[token_key] = token_val
        try:
            resp = fn(**kw)
        except (ClientError, BotoCoreError):
            return
        for k, v in resp.items():
            if k != "ResponseMetadata" and isinstance(v, list):
                yield from v
                break
        if resp.get("nextToken"):
            token_key, token_val = "nextToken", resp["nextToken"]
        elif resp.get("NextToken"):
            token_key, token_val = "NextToken", resp["NextToken"]
        else:
            return


def wait_until(pred, attempts=30, delay=5, label=""):
    """Poll pred() until truthy or the budget ends; announce a timeout."""
    for _ in range(attempts):
        try:
            if pred():
                return True
        except (ClientError, BotoCoreError):
            pass
        time.sleep(delay)
    if label:
        log(f"  WARNING: {label} not confirmed within the wait budget.")
    return False


def make_session(region, profile=None):
    try:
        session = boto3.session.Session(region_name=region, profile_name=profile or None)
        if profile:
            session.get_credentials()
        return session
    except ProfileNotFound:
        log(f"AWS profile '{profile}' was not found in your AWS config.")
        raise SystemExit(1) from None


def caller_identity(session, region):
    """Return the sts get-caller-identity dict, or exit with advice."""
    try:
        ident = session.client("sts", region_name=region).get_caller_identity()
    except (ClientError, NoCredentialsError, BotoCoreError) as e:
        log(f"Could not resolve AWS credentials: {e}")
        log("Configure credentials the way the AWS CLI does (profile, SSO, env vars,")
        log("instance role) -- this tool reads the same chain. --profile <name> works too.")
        raise SystemExit(1) from None
    global _warned_root
    if ident.get("Arn", "").endswith(":root") and not _warned_root:
        _warned_root = True
        log("WARNING: running as the account ROOT user -- use an IAM user or role instead.")
    return ident


def resolve_account(session, region):
    return caller_identity(session, region)["Account"]


def _ca_bundle_candidates():
    try:
        import certifi

        yield certifi.where()
    except ImportError:
        pass
    try:
        import botocore

        p = os.path.join(os.path.dirname(botocore.__file__), "cacert.pem")
        if os.path.exists(p):
            yield p
    except ImportError:
        pass


def tls_context(extra_ca_file=None):
    """Verified TLS context for stdlib HTTPS. Falls back to certifi/botocore's
    CA bundle when the interpreter's store is empty; optionally also trusts
    `extra_ca_file` (the stack's self-signed ALB certificate). Verification is
    never disabled."""
    global _TLS_CONTEXT
    if _TLS_CONTEXT is not None and not extra_ca_file:
        return _TLS_CONTEXT
    ctx = ssl.create_default_context()
    if not ctx.cert_store_stats().get("x509_ca"):
        for cafile in _ca_bundle_candidates():
            try:
                candidate = ssl.create_default_context(cafile=cafile)
            except (ssl.SSLError, OSError):
                continue
            if candidate.cert_store_stats().get("x509_ca"):
                ctx = candidate
                break
    if extra_ca_file:
        ctx.load_verify_locations(cafile=extra_ca_file)
        return ctx
    _TLS_CONTEXT = ctx
    return ctx
