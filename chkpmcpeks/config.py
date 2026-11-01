"""Single source of truth: the @chkp server catalog, credential shapes, and
every resource name the EKS stack uses.

The catalog, credential shapes, default server set, and the `chkp/<server>`
secret naming are ported from the AgentCore reference project
(checkpoint-mcp-on-aws-agentcore, chkpmcpaws/config.py) so credentials carry
over unchanged: the same Secrets Manager secrets and the same
`chkp-credentials.env` file work for both projects.

The Helm chart's `servers:` map (charts/checkpoint-mcp/values.yaml) mirrors
SERVER_CATALOG; tests/test_catalog_parity.py fails CI if the two drift.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

DEFAULT_REGION = "us-east-1"
PROJECT_TAG = "chkp-mcp-eks"
DEFAULT_ENV_FILE = ".env"

# Tools are exposed by agentgateway as <target><SEP><tool>; target names are the
# server name without hyphens. agentgateway's separator is a single underscore
# and target names cannot contain one, so the FIRST underscore is the boundary.
# (The AgentCore project uses "___"; the agent reads TOOL_SEPARATOR so the same
# loop works against either gateway.)
TOOL_SEPARATOR = "_"

# --------------------------------------------------------------------------
# The @chkp MCP servers we host (15 of the 18 upstream). `creds` names the
# credential SHAPE wired into the container as env vars (None = no container
# secret). Every credentialed server gets its OWN chkp/<server> secret.
# `version` pins the npm package so a deploy is reproducible.
# `remote` notes caveats for hosting the server remotely (behind a gateway).
# --------------------------------------------------------------------------
SERVER_CATALOG = {
    # -- Management-shaped: same env var NAMES, separate secret each ----------
    "quantum-management": {"creds": "management", "version": "1.4.7"},
    "management-logs":    {"creds": "management", "version": "1.4.6"},
    "threat-prevention":  {"creds": "management", "version": "1.5.4"},
    "https-inspection":   {"creds": "management", "version": "1.4.6"},
    "policy-insights":    {"creds": "management", "version": "0.3.5"},
    "quantum-gw-cli":     {"creds": "management", "version": "1.4.8"},
    # -- Product-specific credentials ---------------------------------------
    "reputation-service": {"creds": "reputation-service", "version": "1.3.1"},
    "threat-emulation":   {"creds": "threat-emulation", "version": "1.3.1",
                           "note": "hash/URL lookups work remotely; uploading a LOCAL file does not (the pod can't see your disk)"},
    "cloudguard-waf":     {"creds": "cloudguard-waf", "version": "0.1.0"},
    "argos-erm":          {"creds": "argos-erm", "version": "0.5.4", "exclude_from_all": True,
                           "note": "needs real Argos creds to list tools (excluded from 'all')"},
    "spark-management":   {"creds": "spark-management", "version": "1.4.8"},
    "harmony-sase":       {"creds": "harmony-sase", "version": "1.3.1", "exclude_from_all": True,
                           "note": "Harmony SASE API key + management host/origin (validate on your tenant)"},
    "workforce-ai":       {"creds": "workforce-ai", "version": "1.1.0", "exclude_from_all": True,
                           "note": "CloudInfra API key (client id + access key + gateway URL)"},
    # quantum-gaia authenticates ONLY via interactive MCP elicitation, which a
    # stateless multiplexing gateway cannot relay -- same limitation as the
    # AgentCore Gateway. Deployable by name; its calls will not authenticate.
    "quantum-gaia":       {"creds": None, "version": "1.3.5", "exclude_from_all": True,
                           "note": "interactive-only auth; can't authenticate through a gateway"},
    "documentation":      {"creds": "documentation", "version": "1.4.6", "args": "--region US",
                           "note": "Infinity Portal API key + --region (set automatically)"},
}

# Placeholder secret body per credential SHAPE (env-var key names from each
# package README). Never a real credential. A server boots on these and fails
# auth cleanly until real creds are applied (`chkpmcpeks creds apply`).
CRED_SHAPE = {
    "management": {"MANAGEMENT_HOST": "127.0.0.1", "MANAGEMENT_PORT": "443",
                   "API_KEY": "PLACEHOLDER_NOT_A_REAL_KEY"},
    "reputation-service": {"API_KEY": "PLACEHOLDER_NOT_A_REAL_KEY"},
    "threat-emulation": {"API_KEY": "PLACEHOLDER_NOT_A_REAL_KEY"},
    "cloudguard-waf": {"WAF_CLIENT_ID": "PLACEHOLDER", "WAF_ACCESS_KEY": "PLACEHOLDER",
                       "WAF_REGION": "eu-west-1"},
    "argos-erm": {"ARGOS_API_KEY": "PLACEHOLDER", "ARGOS_CUSTOMER_ID": "PLACEHOLDER"},
    "spark-management": {"CLIENT_ID": "PLACEHOLDER", "SECRET_KEY": "PLACEHOLDER",
                         "INFINITY_PORTAL_URL": "https://portal.checkpoint.com"},
    "harmony-sase": {"API_KEY": "PLACEHOLDER_NOT_A_REAL_KEY",
                     "MANAGEMENT_HOST": "https://api.your-management-host.com/api",
                     "ORIGIN": "https://your.origin-domain.com"},
    "workforce-ai": {"CP_CI_CLIENT_ID": "PLACEHOLDER", "CP_CI_ACCESS_KEY": "PLACEHOLDER",
                     "CP_CI_GATEWAY": "https://cloudinfra-gw-us.portal.checkpoint.com"},
    "documentation": {"CLIENT_ID": "PLACEHOLDER", "SECRET_KEY": "PLACEHOLDER"},
}

# Same default 9 as the reference project: the six management-shaped servers,
# the ThreatCloud pair, and documentation.
DEFAULT_SERVERS = ("quantum-management", "management-logs", "threat-prevention",
                   "https-inspection", "policy-insights", "quantum-gw-cli",
                   "reputation-service", "threat-emulation", "documentation")

# Tool-name fragments treated as MUTATING when the chart's read-only policy is
# on (toolPolicy.readOnly). Matched against the tool part of <target>_<tool>.
# Kept here so unit tests and the chart template share one list.
MUTATING_TOOL_PATTERNS = (
    "add_", "set_", "delete_", "remove_", "update_", "create_", "edit_",
    "publish", "install_", "discard", "approve", "reject", "submit",
    "quarantine", "restore", "release", "run_script", "execute", "assign_",
    "unlock", "lock_", "reset_", "enable_", "disable_",
)

_PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]{0,11}$")


def parse_servers(text):
    """Split a space- or comma-separated server list into a tuple. The literal
    `all` expands to every catalog server not flagged exclude_from_all."""
    if not text:
        return ()
    if text.strip().lower() == "all":
        return tuple(s for s, m in SERVER_CATALOG.items() if not m.get("exclude_from_all"))
    return tuple(text.replace(",", " ").split())


def target_name(server, prefix=""):
    """agentgateway target name -> tool namespace (<target>_<tool>).
    Hyphens are dropped (target names may not contain '_' either)."""
    base = server.replace("-", "")
    return (prefix.replace("-", "") + base) if prefix else base


def split_tool_name(name, separator=TOOL_SEPARATOR):
    """'reputationservice_get_url_reputation' -> ('reputationservice', 'get_url_reputation').
    Returns (None, name) when the name carries no namespace."""
    head, sep, tail = name.partition(separator)
    if not sep or not head or not tail:
        return None, name
    return head, tail


def is_mutating_tool(tool, patterns=MUTATING_TOOL_PATTERNS):
    """True if the (un-namespaced) tool name looks like it changes state."""
    t = tool.lower()
    return any(p in t for p in patterns)


def load_env_file(path=DEFAULT_ENV_FILE):
    """Load KEY=VALUE lines from a local .env into os.environ (an already
    exported variable always wins). Skips comments and [section] headers.
    Returns the list of key NAMES set; values are never logged."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    loaded = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#", "[")):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, eq, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if not eq or not key:
            continue
        if val[:1] in ("'", '"'):
            end = val.find(val[0], 1)
            val = val[1:end] if end != -1 else val[1:]
        if key not in os.environ:
            os.environ[key] = val
            loaded.append(key)
    return loaded


@dataclass(frozen=True)
class StackConfig:
    region: str = DEFAULT_REGION
    prefix: str = ""
    servers: tuple = DEFAULT_SERVERS
    extra_tags: dict = field(default_factory=dict)

    def validate(self):
        if self.prefix and not _PREFIX_RE.match(self.prefix):
            raise ValueError("--prefix must match [a-z][a-z0-9-]{0,11}")
        if not self.servers:
            raise ValueError("no servers selected")
        unknown = [s for s in self.servers if s not in SERVER_CATALOG]
        if unknown:
            raise ValueError("unknown server(s): " + ", ".join(unknown)
                             + ". Known servers: " + ", ".join(sorted(SERVER_CATALOG)))

    # -- names ---------------------------------------------------------------
    def _dash(self, base):
        return f"{base}-{self.prefix}" if self.prefix else base

    @property
    def cluster_name(self):
        return self._dash("chkp-mcp-eks")

    @property
    def namespace(self):
        return "chkp-mcp"

    @property
    def helm_release(self):
        return "checkpoint-mcp"

    @property
    def stack_tag(self):
        return self.prefix or "default"

    @property
    def ecr_server_repo(self):
        return f"{self.cluster_name}/mcp-server"

    @property
    def ecr_agent_repo(self):
        return f"{self.cluster_name}/agent"

    def tags(self):
        t = {"project": PROJECT_TAG, "stack": self.stack_tag}
        t.update(self.extra_tags)
        return t

    def tags_kv(self, key="Key", value="Value"):
        return [{key: k, value: v} for k, v in self.tags().items()]

    # -- per-server ----------------------------------------------------------
    def secret_name(self, server):
        """Same naming as the AgentCore project so the secrets are shared."""
        return self._dash(f"chkp/{server}")

    def server_needs_creds(self, server):
        return SERVER_CATALOG.get(server, {}).get("creds") is not None

    def servers_with_creds(self, servers=None):
        return [s for s in (servers or self.servers) if self.server_needs_creds(s)]

    def placeholder_for(self, server):
        shape = SERVER_CATALOG.get(server, {}).get("creds")
        return dict(CRED_SHAPE.get(shape, {})) if shape else {}

    def pkg_spec(self, server):
        version = SERVER_CATALOG[server].get("version")
        base = f"@chkp/{server}-mcp"
        return f"{base}@{version}" if version else base

    def servers_version(self, server):
        return SERVER_CATALOG[server]["version"]

    def image_tag(self, server):
        """Immutable per-server tag in the shared mcp-server ECR repo."""
        return f"{server}-{SERVER_CATALOG[server]['version']}"

    def startup_args(self, server):
        return SERVER_CATALOG.get(server, {}).get("args", "")

    def target_name(self, server):
        return target_name(server, self.prefix)

# Every request header name an @chkp package reads credentials/settings from
# (extracted from CheckPointSW/mcp-servers `getHeaderValue(...)` calls). Used as
# a defense-in-depth DENY list; the primary control is the gateway's header
# ALLOW list (only MCP protocol headers reach a backend). Refresh this list when
# bumping package versions: see docs/runbooks/upgrade.md.
CHKP_CREDENTIAL_HEADERS = (
    "api-key", "argos-api-key", "argos-customer-id", "argos-host", "argos-integration-token",
    "argos-server-url", "auth-url", "client-id", "cloud-connected", "cloud-infra-token",
    "cp-ci-access-key", "cp-ci-client-id", "cp-ci-gateway", "dev-port", "doc-source",
    "doc-tool-client-id", "doc-tool-region", "doc-tool-secret-key", "gateway-url",
    "infinity-portal-url", "management-domain", "management-host", "management-port", "origin",
    "password", "region", "s1c-url", "secret-key", "username", "verbose", "waf-access-key",
    "waf-allow-writes", "waf-client-id", "waf-region", "x-chkp-sid",
)
