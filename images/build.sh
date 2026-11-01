#!/usr/bin/env bash
# Build, smoke-test and push the stack's images. Runs on AWS CodeBuild (arm64)
# from `chkpmcpeks build`, or anywhere with Docker and an ECR login.
#
# Inputs (environment):
#   REGISTRY       <account>.dkr.ecr.<region>.amazonaws.com
#   SERVER_REPO    ECR repo for MCP server images   (e.g. chkp-mcp-eks/mcp-server)
#   AGENT_REPO     ECR repo for the agent image     (e.g. chkp-mcp-eks/agent)
#   SERVER_BUILDS  space-separated server=version   (e.g. "reputation-service=1.3.1")
#   AGENT_TAG      tag for the agent image, or empty to skip it
#   ARGS_<server>  startup flags for a server's smoke test, hyphens as underscores
#                  (e.g. ARGS_documentation="--region US")
#   PLATFORM       docker platform (default linux/arm64)
set -euo pipefail
PLATFORM="${PLATFORM:-linux/arm64}"
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"
failed=()

smoke() {   # smoke <image> <name>: /health must answer; tools/list is reported
  local image="$1" name="$2" port=18000 sid status args_var
  args_var="ARGS_${name//-/_}"
  docker run -d --name "smoke-$name" -p "$port:8000" -e API_KEY=PLACEHOLDER \
    -e "CHKP_ARGS=${!args_var:-}" \
    -e MANAGEMENT_HOST=127.0.0.1 -e CLIENT_ID=PLACEHOLDER -e SECRET_KEY=PLACEHOLDER \
    --read-only --tmpfs /tmp --user 1000:1000 --cap-drop ALL "$image" >/dev/null
  for _ in $(seq 1 30); do
    status="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/health" || true)"
    [ "$status" = "200" ] && break
    sleep 1
  done
  if [ "$status" != "200" ]; then
    echo "SMOKE FAIL $name: /health returned '$status'"; docker logs "smoke-$name" | tail -40 || true
    docker rm -f "smoke-$name" >/dev/null 2>&1 || true
    return 1
  fi
  sid="$(curl -s -D - -o /dev/null -X POST "http://127.0.0.1:$port/mcp" \
      -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}' \
      | tr -d '\r' | awk -F': ' 'tolower($1)=="mcp-session-id"{print $2}')"
  if [ -n "$sid" ]; then
    curl -s -o /dev/null -X POST "http://127.0.0.1:$port/mcp" -H "mcp-session-id: $sid" \
      -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
      -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' || true
    tools="$(curl -s -X POST "http://127.0.0.1:$port/mcp" -H "mcp-session-id: $sid" \
      -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
      -H 'mcp-protocol-version: 2025-06-18' \
      -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | grep -o '"name":"[^"]*"' | wc -l || true)"
    echo "SMOKE OK   $name: /health 200, tools/list returned ${tools// /} tool names"
  else
    echo "SMOKE OK   $name: /health 200 (initialize gave no session id; tools/list skipped)"
  fi
  docker rm -f "smoke-$name" >/dev/null 2>&1 || true
}

for item in ${SERVER_BUILDS:-}; do
  server="${item%%=*}"; version="${item#*=}"
  image="$REGISTRY/$SERVER_REPO:$server-$version"
  echo "=== building $image"
  if ! docker build --platform "$PLATFORM" --build-arg "CHKP_SERVER=$server" \
        --build-arg "CHKP_VERSION=$version" -t "$image" "$here/mcp-server"; then
    failed+=("$server (build)"); continue
  fi
  if ! smoke "$image" "$server"; then failed+=("$server (smoke)"); continue; fi
  docker push "$image" | tail -1
done

if [ -n "${AGENT_TAG:-}" ]; then
  image="$REGISTRY/$AGENT_REPO:$AGENT_TAG"
  echo "=== building $image"
  if docker build --platform "$PLATFORM" -t "$image" "$root/services/agent"; then
    docker push "$image" | tail -1
  else
    failed+=("agent (build)")
  fi
fi

if [ "${#failed[@]}" -gt 0 ]; then
  echo "FAILED: ${failed[*]}"; exit 1
fi
echo "ALL IMAGES BUILT"
