#!/bin/sh
# Start the baked-in @chkp MCP server in streamable-HTTP mode. Node runs the
# package entrypoint directly -- no npm/npx at runtime, so the root filesystem
# can be read-only (only /tmp is writable, from an emptyDir).
set -eu
entry="$(cat /etc/chkp-entry)"
# shellcheck disable=SC2086  # CHKP_ARGS is intentionally word-split into flags
exec node "${entry}" --transport http --transport-port "${MCP_TRANSPORT_PORT:-8000}" --no-telemetry ${CHKP_ARGS:-}
