# ADR 0003: External Secrets Operator syncing from AWS Secrets Manager

**Status:** accepted, 2026-11-01

## Context

Each `@chkp` server reads its Check Point credentials from **environment variables**. The AgentCore project already stores one Secrets Manager secret per server, `chkp/<server>`, holding a JSON object of those variables. Customers must be able to reuse those secrets and the same `chkp-credentials.env` file.

## Options considered

| Option | Verdict |
|---|---|
| **External Secrets Operator (ESO)** | Syncs a Secrets Manager JSON secret into a Kubernetes Secret (one key per field), consumed with `envFrom`. Pod Identity on the controller; namespaced `SecretStore`. Provider-agnostic (Vault, Azure Key Vault, GCP). |
| Secrets Store CSI Driver + AWS provider | Mounts secrets as files. Env vars would still need its "sync as Kubernetes Secret" feature, so it adds a CSI driver and a volume per pod for no gain. |

## Decision

ESO 2.14 (`external-secrets.io/v1`). One `ExternalSecret` per credentialed server with `dataFrom.extract.key: chkp/<server>`, refreshed every minute. A namespaced `SecretStore` uses the ESO controller's EKS Pod Identity. The IAM role reads only `chkp/*` and this stack's own secrets.

## Consequences

- Credentials carry over unchanged from the AgentCore project.
- Terraform reads `chkp/*` only as data and never owns them, and `destroy` never deletes them.
- `creds apply` writes Secrets Manager and annotates the ExternalSecret to re-sync immediately. **Stakater Reloader**, scoped to the namespace, then restarts only the affected server, because env vars are read at process start.
- ESO had maintainer turnover in 2025. The chart version is pinned, and the CSI driver remains a documented fallback.
