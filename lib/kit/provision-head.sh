#!/bin/bash
set -euo pipefail
# TEMPLATE: set STEP_TOTAL to the number of step calls and EXPECTED_MIN to the measured minutes;
# align_lint.py fails 0 in either.

STARTED=$(date +%s); STEP_TOTAL=0; STEP_N=0; STEP_LABEL="Starting"; EXPECTED_MIN=0   # measured cold-start provisioning minutes, rounded up (cite the runs)
step() {
  STEP_N=$((STEP_N + 1)); STEP_LABEL="$1"
  echo "STEP: $STEP_LABEL"
  printf '{"ready": false, "step": "%s", "step_n": %d, "step_total": %d, "started": %d, "expected_min": %d}\n' \
    "$STEP_LABEL" "$STEP_N" "$STEP_TOTAL" "$STARTED" "$EXPECTED_MIN" > /opt/ara/brief/status.json
}
trap '_code=$?
  printf "%s\n" "{\"ready\": false, \"error\": \"${STEP_LABEL}\", \"step_n\": ${STEP_N}, \"step_total\": ${STEP_TOTAL}}" \
    > /opt/ara/brief/status.json
  tail -40 /var/log/ara-provision.log > /opt/ara/.failed 2>/dev/null || true
  chmod 600 /opt/ara/.failed 2>/dev/null || true
  exit $_code' ERR
