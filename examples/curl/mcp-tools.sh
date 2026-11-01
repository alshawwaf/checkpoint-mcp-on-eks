#!/usr/bin/env bash
# Talk MCP (JSON-RPC over streamable HTTP) to the gateway with plain curl:
# initialize, list the tools, and call one reputation lookup.
# Needs the same CHKP_* variables as ask-agent.sh.
set -euo pipefail
ca=()
if [ -n "${CHKP_CA_FILE:-}" ]; then ca=(--cacert "$CHKP_CA_FILE"); fi
token="$(curl -fsS -u "$CHKP_CLIENT_ID:$CHKP_CLIENT_SECRET" \
  -d "grant_type=client_credentials&scope=$CHKP_SCOPE" "$CHKP_TOKEN_URL" |
  python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"

rpc() {  # rpc <json-body>  -> prints the JSON-RPC result (SSE or JSON response)
  curl -fsS "${ca[@]}" "$CHKP_MCP_URL" -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
    -H "mcp-protocol-version: 2025-06-18" -d "$1" |
    python -c 'import sys
body = sys.stdin.read()
data = [l[5:].strip() for l in body.splitlines() if l.startswith("data:")]
print(data[-1] if data else body.strip())'   # SSE or plain JSON -> one JSON object
}

echo "== initialize"
rpc '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}' |
  python -c 'import json,sys; r=json.loads(sys.stdin.read()); print(r["result"]["serverInfo"])'

echo "== tools/list (first 15)"
rpc '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' |
  python -c 'import json,sys; r=json.loads(sys.stdin.read()); [print("  ", t["name"]) for t in r["result"]["tools"][:15]]; print("   total:", len(r["result"]["tools"]))'

echo "== tools/call reputationservice_reputation_url"
rpc '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"reputationservice_reputation_url","arguments":{"resource":"https://www.checkpoint.com"}}}' |
  python -c 'import json,sys; r=json.loads(sys.stdin.read()); print("  ", r["result"]["content"][0]["text"][:400])'
