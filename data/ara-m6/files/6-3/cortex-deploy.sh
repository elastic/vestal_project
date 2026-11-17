#!/bin/bash
# Cortex's deploy script: applies one change to Tina through the Agent Builder API and records it in cortex-change-log.
# Usage: cortex-deploy.sh --change-id <id> --change-file <file.json>
# The file holds {"kind": "agent" | "tool", "id": "<object id>", "body": {...the fields to PUT...}}.
set -euo pipefail
source "${HOME}/env"
CHANGE_ID=""; CHANGE_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --change-id) CHANGE_ID="$2"; shift 2 ;;
    --change-file) CHANGE_FILE="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$CHANGE_ID" && -f "$CHANGE_FILE" ]] || { echo "usage: cortex-deploy.sh --change-id <id> --change-file <file.json>" >&2; exit 2; }
KIND=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kind"])' "$CHANGE_FILE")
OBJ=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$CHANGE_FILE")
BODY=$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["body"]))' "$CHANGE_FILE")
curl -sS -f -X PUT "$KIBANA_URL/api/agent_builder/${KIND}s/$OBJ" -H "Authorization: ApiKey $ES_API_KEY" -H "kbn-xsrf: true" -H "Content-Type: application/json" -d "$BODY" > /dev/null
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
curl -sS -f -X POST "$ES_URL/cortex-change-log/_doc?refresh=wait_for" -H "Authorization: ApiKey $ES_API_KEY" -H "Content-Type: application/json" \
  -d "{\"at\": \"$NOW\", \"kind\": \"deploy\", \"object\": \"$OBJ\", \"change_id\": \"$CHANGE_ID\", \"actor\": \"cortex-ops\"}" > /dev/null
echo "deployed $OBJ as $CHANGE_ID"
# >>> AFTER DEPLOY: add what should run after a deploy; $CHANGE_ID is this deploy's change id >>>
# <<< AFTER DEPLOY <<<
