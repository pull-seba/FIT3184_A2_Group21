#!/usr/bin/env bash
# Calls every API route with no token and with a bad token, and expects 401 from API Gateway each time.
# Rubric 1.2: unauthenticated callers must be blocked from every endpoint.
#
# Usage: API_BASE=https://<gateway-host> scripts/check-no-token.sh
# Keep ROUTES in step with docs/contracts/api-routes.md (/contract-check flags drift).
set -uo pipefail

: "${API_BASE:?Set API_BASE to the gateway URL, for example https://ecoguard-abc123.ts.gateway.dev}"
base="${API_BASE%/}"
dummy_id="0000000000000000000000000000000000000000000000000000000000000000"

ROUTES=(
  "POST /uploads/init"
  "GET /files/${dummy_id}"
  "POST /files/delete"
  "POST /search/tags"
  "GET /search/species?name=cat"
  "POST /search/thumbnail"
  "POST /search/by-file"
  "POST /search/lost-pet"
  "POST /tags/bulk"
  "GET /notifications/subscriptions"
  "PUT /notifications/subscriptions"
)

failures=0

check() {
  local label="$1" method="$2" path="$3"
  shift 3
  local args=(-s -o /dev/null -w '%{http_code}' -X "$method" "$@")
  if [[ "$method" != "GET" ]]; then
    args+=(-H 'Content-Type: application/json' -d '{}')
  fi
  local code
  code=$(curl "${args[@]}" "${base}${path}")
  if [[ "$code" == "401" ]]; then
    printf 'ok    %s  %-6s %s (%s)\n' "$code" "$method" "$path" "$label"
  else
    printf 'FAIL  %s  %-6s %s (%s, expected 401)\n' "$code" "$method" "$path" "$label"
    failures=$((failures + 1))
  fi
}

for route in "${ROUTES[@]}"; do
  method="${route%% *}"
  path="${route#* }"
  check "no token" "$method" "$path"
  check "bad token" "$method" "$path" -H 'Authorization: Bearer not-a-real-token'
done

if (( failures > 0 )); then
  echo "${failures} check(s) failed"
  exit 1
fi
echo "Every route rejected calls without a valid token"
