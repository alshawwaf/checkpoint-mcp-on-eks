# syntax=docker/dockerfile:1
# One image per Check Point MCP server, built from the PUBLISHED, version-pinned
# npm package (@chkp/<server>-mcp@<version>). The package is installed at build
# time, so nothing is fetched at runtime and each image can be pinned by digest.
#
#   docker build --build-arg CHKP_SERVER=reputation-service --build-arg CHKP_VERSION=1.3.1 .
#
# Runtime contract (same as the AgentCore project's image):
#   - streamable HTTP MCP on :8000 at / and /mcp, health on /health
#   - credentials arrive as environment variables (the chart's ExternalSecret)
#   - extra startup flags in CHKP_ARGS (e.g. documentation needs --region US)
ARG BASE_IMAGE=public.ecr.aws/docker/library/node:24-slim
FROM ${BASE_IMAGE}

ARG CHKP_SERVER
ARG CHKP_VERSION
ARG NPM_REGISTRY=https://registry.npmjs.org/

ENV NODE_ENV=production \
    TELEMETRY_DISABLED=true \
    MCP_TRANSPORT_TYPE=http \
    MCP_TRANSPORT_PORT=8000 \
    HOME=/tmp \
    npm_config_cache=/tmp/.npm \
    CHKP_SERVER=${CHKP_SERVER} \
    CHKP_VERSION=${CHKP_VERSION}

# --ignore-scripts: the published packages need no install hooks, and running
# none removes a whole class of supply-chain risk at build time.
RUN set -eux; \
    test -n "${CHKP_SERVER}" && test -n "${CHKP_VERSION}"; \
    npm install -g --ignore-scripts --no-audit --no-fund --registry "${NPM_REGISTRY}" \
        "@chkp/${CHKP_SERVER}-mcp@${CHKP_VERSION}"; \
    entry="$(npm root -g)/@chkp/${CHKP_SERVER}-mcp/dist/index.js"; \
    test -f "${entry}"; \
    printf '%s' "${entry}" > /etc/chkp-entry; \
    npm cache clean --force; \
    rm -rf /tmp/.npm /root/.npm

COPY --chmod=0755 entrypoint.sh /usr/local/bin/chkp-entrypoint

LABEL org.opencontainers.image.title="chkp-mcp-${CHKP_SERVER}" \
      org.opencontainers.image.version="${CHKP_VERSION}" \
      org.opencontainers.image.description="@chkp/${CHKP_SERVER}-mcp over streamable HTTP" \
      org.opencontainers.image.source="https://github.com/alshawwaf/checkpoint-mcp-on-eks" \
      org.opencontainers.image.licenses="MIT"

# The official node image ships an unprivileged `node` user (uid 1000).
USER 1000:1000
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/chkp-entrypoint"]
