# ADR 0007: One image per server, built from the published npm package

**Status:** accepted, 2026-11-01

## Context

The AgentCore project runs **one generic image** that calls `npx -y @chkp/<server>-mcp@<version>` at container start and reads its secret from Secrets Manager itself.

## Decision

A new `images/mcp-server/Dockerfile` builds **one image per server**. The image installs the pinned package `@chkp/<server>-mcp@<version>` at build time, with `--ignore-scripts`. It is based on `node:24-slim` from the public ECR mirror, runs as uid 1000, and its entrypoint execs `node` directly.

## Why not reuse the AgentCore image

| | AgentCore generic image | Per-server image (this repo) |
|---|---|---|
| Package fetched | at every container start | once, at build time |
| Digest pinning | one digest for all servers; package resolved at runtime | each server pinned by digest |
| Read-only root filesystem | no (npx writes a cache) | yes |
| Secrets | pod calls Secrets Manager itself | injected as env by ESO; pods hold no AWS credentials |
| Start time | slow (npm download) | fast |

## Kept in step with the AgentCore project

The **runtime contract** is identical, so both projects stay in step:

- the same env var names, from the same `chkp/<server>` secrets;
- `--transport http` on port 8000;
- `CHKP_ARGS` for extra flags, such as documentation's `--region US`;
- the same pinned versions in the catalog.

## Build

`chkpmcpeks build` runs on CodeBuild (arm64). Every image is smoke-tested before push: run non-root on a read-only root filesystem with `cap-drop ALL`, require `/health` to return 200, and report the `tools/list` count. Tags are immutable and content-derived (`<server>-<version>`, `agent-<sha>`), so existing images are never rebuilt. `build-images.yml` builds multi-arch (arm64 + amd64) from GitHub Actions via OIDC.
