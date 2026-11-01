#!/usr/bin/env bash
# Ask the Check Point security-ops agent a question over HTTPS.
# Needs: CHKP_TOKEN_URL CHKP_CLIENT_ID CHKP_CLIENT_SECRET CHKP_SCOPE CHKP_AGENT_URL [CHKP_CA_FILE]
#   eval "$(python -m chkpmcpeks endpoints --format sh --reveal-secret)"
set -euo pipefail
question="${1:-What is the reputation of https://www.checkpoint.com?}"
ca=()
if [ -n "${CHKP_CA_FILE:-}" ]; then ca=(--cacert "$CHKP_CA_FILE"); fi

token="$(curl -fsS -u "$CHKP_CLIENT_ID:$CHKP_CLIENT_SECRET" \
  -d "grant_type=client_credentials&scope=$CHKP_SCOPE" "$CHKP_TOKEN_URL" |
  python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"

body="$(python -c 'import json,sys; print(json.dumps({"prompt": sys.argv[1]}))' "$question")"
curl -fsS "${ca[@]}" "$CHKP_AGENT_URL" \
  -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d "$body" |
  python -c '
import json, sys
r = json.load(sys.stdin)
print("model :", r.get("model"))
print("tools :", ", ".join(t["name"] for t in r.get("tool_calls", [])) or "none")
print("usage :", r.get("usage"))
print()
print(r.get("result"))'
