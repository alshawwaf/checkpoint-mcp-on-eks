# Security policy

This repository is a reference architecture. It is not a supported Check Point product.

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Report them privately through
[GitHub security advisories](https://github.com/alshawwaf/checkpoint-mcp-on-eks/security/advisories/new).

Vulnerabilities in the `@chkp` MCP server packages themselves belong upstream at
[CheckPointSW/mcp-servers](https://github.com/CheckPointSW/mcp-servers).

## Before you use real credentials

Read [docs/security.md](docs/security.md). It covers the trust boundaries, the gateway's header
allow-list and read-only tool policy, and known upstream issues such as on-prem management TLS
verification.
