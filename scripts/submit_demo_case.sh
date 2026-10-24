#!/usr/bin/env bash
# Submit one case from backend/tests/fixtures/demo_cases.yaml through the real API.
# Usage: ./submit_demo_case.sh DEMO_4 [email] [password]
set -euo pipefail

CASE_ID="${1:?Usage: $0 <case_id, e.g. DEMO_4> [email] [password]}"
EMAIL="${2:-intake@triageai.local}"
PASSWORD="${3:-traigeintake123}"
BASE="http://localhost:8000/api/v1"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

echo "== 1. Building the payload for $CASE_ID from the fixture =="
PAYLOAD="$(docker compose exec -T backend python3 -c "
import json, sys, yaml

CASE_ID = '$CASE_ID'
document = yaml.safe_load(open('tests/fixtures/demo_cases.yaml'))

# demo_cases.yaml is a dict with a top-level 'cases:' key holding the list of
# scenarios (confirmed from app/pipeline/mock_fixtures.py's own load_fixtures():
# 'document.get(\"cases\") or []'). This mirrors that exact access, so this
# script can never disagree with what the mock stages themselves read.
case = next((c for c in (document.get('cases') or []) if c.get('id') == CASE_ID), None)

if case is None:
    sys.exit(f'No case with id {CASE_ID} under the cases: key in demo_cases.yaml')

body = {
    'species': case['species'],
    'intake_channel': case.get('intake_channel'),
    'description': case['description'].strip(),
}
if 'signalment' in case:
    body['signalment'] = case['signalment']
print(json.dumps(body))
")"
echo "$PAYLOAD" | python3 -m json.tool

echo; echo "== 2. Logging in as $EMAIL =="
LOGIN_RESP="$(curl -sS -c "$JAR" -b "$JAR" -X POST "$BASE/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")"
echo "$LOGIN_RESP" | python3 -m json.tool

CSRF="$(grep -i triageai_csrf "$JAR" | awk '{print $NF}')"
if [ -z "$CSRF" ]; then
  echo "No triageai_csrf cookie came back — login failed (wrong password, account" >&2
  echo "locked, or must_change_password is still true for this account)." >&2
  exit 1
fi

echo; echo "== 3. Submitting the case =="
curl -sS -c "$JAR" -b "$JAR" -X POST "$BASE/cases" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d "$PAYLOAD" | python3 -m json.tool
