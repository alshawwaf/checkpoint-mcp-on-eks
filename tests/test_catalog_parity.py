"""The Helm chart's values.yaml must mirror chkpmcpeks/config.py exactly: same
servers, versions, credential flags, startup args, default set, read-only
patterns and credential-header deny-list."""

import os

import yaml

from chkpmcpeks import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALUES = yaml.safe_load(open(os.path.join(ROOT, "charts", "checkpoint-mcp", "values.yaml"), encoding="utf-8"))


def test_servers_match_catalog():
    chart = VALUES["servers"]
    assert set(chart) == set(config.SERVER_CATALOG)
    for server, meta in config.SERVER_CATALOG.items():
        c = chart[server]
        assert c["version"] == meta["version"], server
        assert c["creds"] is (meta["creds"] is not None), server
        assert c.get("args", "") == meta.get("args", ""), server
        assert c["enabled"] is (server in config.DEFAULT_SERVERS), server


def test_policy_lists_match():
    assert tuple(VALUES["toolPolicy"]["mutatingPatterns"]) == config.MUTATING_TOOL_PATTERNS
    assert tuple(VALUES["agentgateway"]["denyHeaders"]) == config.CHKP_CREDENTIAL_HEADERS


def test_forward_headers_exclude_every_credential_header():
    fwd = set(VALUES["agentgateway"]["forwardHeaders"])
    assert not fwd & set(config.CHKP_CREDENTIAL_HEADERS)
    assert "authorization" not in fwd
