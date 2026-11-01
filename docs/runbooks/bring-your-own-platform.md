# Runbook: bring your own platform (GitOps, Okta, Vault, internal registries)

The CLI is the fastest path for a demo. Enterprise platforms usually have their own way of doing each step. The chart and images are built so each piece can be swapped by configuration alone.

## GitOps (Argo CD / Flux)

The chart is plain Helm: no hooks, no CLI-only steps, no lookups against the live cluster. Commit a values file and point Argo CD at `charts/checkpoint-mcp`:

```yaml
images:
  registry: <account>.dkr.ecr.<region>.amazonaws.com
  servers:
    reputation-service: {tag: reputation-service-1.3.1, digest: sha256:...}
  agent: {tag: agent-..., digest: sha256:...}
auth:
  issuer: https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXX
  allowedClientIds: [<external-client-id>, <agent-client-id>]
  resourceUrl: https://mcp.example.com/mcp
agent:
  gatewayTokenUrl: https://<domain>.auth.us-east-1.amazoncognito.com/oauth2/token
ingress:
  certificateArn: arn:aws:acm:...
  host: mcp.example.com
networkPolicy:
  vpcCidr: 10.0.0.0/16
```

`chkpmcpeks deploy` writes exactly these values to `values-images.yaml` and `values-generated.yaml`, so you can copy them into your GitOps repository.

**Promotion and blue/green:** the MCP servers keep session state in memory. A blue/green cutover therefore drops in-flight MCP sessions. With `statefulMode: stateless` the gateway re-opens them on the next request, so clients do not notice. Prefer rolling updates for the server Deployments.

## Okta / Entra ID / Keycloak instead of Cognito

Issue client-credentials tokens from your IdP with a custom scope, then set:

```yaml
auth:
  issuer: https://<org>.okta.com/oauth2/<server-id>
  jwksUrl: https://<org>.okta.com/oauth2/<server-id>/v1/keys
  audience: api://chkp-mcp          # these IdPs set aud; it is then enforced
  allowedClientIds: [<client-id>]
  requiredScope: chkp-mcp/invoke
agent:
  gatewayTokenUrl: https://<org>.okta.com/oauth2/<server-id>/v1/token
```

Put the agent's own client id and secret in the secret named by `agent.clientSecretName`, with keys `GATEWAY_CLIENT_ID` and `GATEWAY_CLIENT_SECRET`.

Browser-redirect SSO, such as Okta at the ingress, does **not** work for MCP or API clients. Keep it token-based.

## HashiCorp Vault (or another secret backend) instead of Secrets Manager

Swap the External Secrets provider. Every `ExternalSecret` keeps working unchanged:

```yaml
secrets:
  prefix: "secret/data/chkp/"
  provider:
    vault:
      server: https://vault.example.com
      path: secret
      version: v2
      auth:
        kubernetes:
          mountPath: kubernetes
          role: chkp-mcp
```

## Internal base images, registries and npm proxies

| Image | Build argument | Example |
|---|---|---|
| MCP servers | `BASE_IMAGE`, `NPM_REGISTRY` | `--build-arg BASE_IMAGE=registry.corp/node:24-alpine --build-arg NPM_REGISTRY=https://nexus.corp/repository/npm/` |
| Agent | `BASE_IMAGE` | `--build-arg BASE_IMAGE=registry.corp/python:3.12-slim` |

Your CI can build with these arguments, push to your registry, and set `images.registry`, `images.serverRepository` and `images.agentRepository`. Keep `--ignore-scripts`: the root `prepare` script of the upstream monorepo runs git commands that fail in a container. Only published packages are installed here, so no install hooks are needed.

## Corporate egress proxy and on-prem management

```yaml
serverDefaults:
  proxy:
    httpsProxy: http://proxy.corp:3128
    noProxy: .svc,.cluster.local,10.0.0.0/8
  egress:
    ports: [443, 3128]
    cidrs: ["10.0.0.0/8", "0.0.0.0/0"]
```
