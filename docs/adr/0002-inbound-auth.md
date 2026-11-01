# ADR 0002: Amazon Cognito for inbound authentication

**Status:** accepted, 2026-11-01

## Context

Both public endpoints, the MCP gateway (`/mcp`) and the agent API (`/v1/chat`), need machine-to-machine authentication that MCP clients, scripts, Postman, n8n and Teams flows can all use.

## Options considered

| Option | Verdict |
|---|---|
| **Amazon Cognito** user pool, client-credentials app clients | Managed, nothing to run in the cluster, per-token pricing only (the per-app-client fee was removed in Nov 2025). Standard OAuth 2.0 token endpoint and JWKS. |
| Keycloak on the cluster | Portable and feature-rich, but adds a database, upgrades and HA to a demo stack. |
| ALB OIDC authentication | Browser authorization-code flow only. MCP and API clients cannot follow redirects to a login page. |

## Decision

Terraform creates a dedicated Cognito user pool with a resource server `chkp-mcp`, scope `invoke`, and two client-credentials app clients:

- `external-clients` for people and tools: the CLI, MCP clients, Postman.
- `agent-internal` for the agent's own calls to the gateway.

## Validation rules

Cognito M2M access tokens carry **no `aud` claim**. Both agentgateway (JWT + CEL) and the agent (PyJWT) therefore check:

- the RS256 signature against the pool's JWKS, and the issuer;
- expiry, and `token_use == access`;
- `client_id` in the allow-list;
- the `scope` string containing `chkp-mcp/invoke`.

## Swapping the issuer

Everything is configuration: `auth.issuer`, `auth.jwksUrl`, `auth.allowedClientIds`, `auth.requiredScope`, plus `auth.audience` for issuers that do set `aud` (Okta, Entra ID, Keycloak). See [Keycloak](../alternatives/keycloak.md) and [bring your own platform](../runbooks/bring-your-own-platform.md).
