"""ara_ops.py - the 6.3 ops scenario variants (28 section 4, O1 to O3) and the B1/B2 schedule checks over the workflow reader.

    scenario(participant_id)                       one of O1 to O3: time zone, shift starts, feed time, desk opening
    shift_occurrences(scn, start, days)            the UTC times a correct shift rule fires in the next `days` days
    window(scn, day)                               N2's window on a UTC date: 15 minutes after the feed lands to 15 before the desk opens
    check_shift_rule(defn, scn, start)             B1 problems (empty when the rule expands to exactly the shifts, no interval trigger)
    check_n2(defn, scn, start)                     B2 N2 problems: a daily occurrence in the window each day, besides the shift rule
    PATTERNS                                       the key for B2's DIAGNOSE (fixed in every variant)

The variants differ in zone, shifts, feed and opening, and are built so that a shift rule never lands in the window
(the desk opens at a shift start, which is 15 minutes after the window closes), and so that a copied rule from
another variant fails. Occurrences are DST-correct through ara_workflow (zoneinfo). Standard library only.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import ara_workflow as W

VARIANTS = (
    {"id": "O1", "tz": "America/New_York", "shift_hours": (6, 14, 22), "feed_utc": "07:30", "desk_open_local": "06:00"},
    {"id": "O2", "tz": "Europe/Berlin", "shift_hours": (7, 15, 23), "feed_utc": "03:00", "desk_open_local": "07:00"},
    {"id": "O3", "tz": "Asia/Singapore", "shift_hours": (0, 8, 16), "feed_utc": "21:30", "desk_open_local": "08:00"},
)
PATTERNS = {"N1": "ad_hoc", "N2": "scheduled", "N3": "per_response"}
MARGIN = timedelta(minutes=15)


def variant_index(participant_id: str) -> int:
    return int(hashlib.sha256(participant_id.encode()).hexdigest(), 16) % 3


def scenario(participant_id: str) -> dict:
    return dict(VARIANTS[variant_index(participant_id)])


def _hm(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


def shift_occurrences(scn: dict, start: datetime, days: int = 7) -> list[datetime]:
    tz = ZoneInfo(scn["tz"])
    first = start.astimezone(tz).date()
    out = []
    for d in range(-1, days + 1):
        for h in scn["shift_hours"]:
            t = datetime.combine(first + timedelta(days=d), time(h), tzinfo=tz).astimezone(timezone.utc)
            if start <= t < start + timedelta(days=days):
                out.append(t)
    return sorted(out)


def window(scn: dict, day) -> tuple[datetime, datetime]:
    """N2's window for the desk opening that follows the feed landing on UTC date `day` (a date): the feed lands at
    feed_utc on `day`; the desk opens at the next desk_open_local in the desk's zone after that."""
    tz = ZoneInfo(scn["tz"])
    feed = datetime.combine(day, _hm(scn["feed_utc"]), tzinfo=timezone.utc)
    local = feed.astimezone(tz)
    opening = datetime.combine(local.date(), _hm(scn["desk_open_local"]), tzinfo=tz)
    if opening <= local:
        opening += timedelta(days=1)
        opening = datetime.combine(opening.date(), _hm(scn["desk_open_local"]), tzinfo=tz)
    return feed + MARGIN, opening.astimezone(timezone.utc) - MARGIN


def _problems_interval(defn: dict) -> list[str]:
    return ["an interval trigger is still on the workflow"] if W.has_interval(defn) else []


def check_shift_rule(defn: dict, scn: dict, start: datetime, days: int = 7, allow_extra: bool = False) -> list[str]:
    """Build 1: the scheduled runs are exactly the shift starts. Build 2 (`allow_extra`): every shift start still has its run and other runs may be added (N2's window run)."""
    bad = _problems_interval(defn)
    got = W.expand(defn, start, start + timedelta(days=days))
    want = shift_occurrences(scn, start, days)
    if (got != want) if not allow_extra else any(t not in got for t in want):
        extra, missing = [t for t in got if t not in want], [t for t in want if t not in got]
        bad.append(f"the scheduled triggers give {len(got)} runs in the next {days} days, the desk's shifts give {len(want)}"
                   + (f"; first run that is not a shift start: {extra[0].isoformat()}" if extra else "")
                   + (f"; first shift start with no run: {missing[0].isoformat()}" if missing else ""))
    return bad


def check_n2(defn: dict, scn: dict, start: datetime, days: int = 7) -> list[str]:
    """The next `days` windows that open after `start` each hold a run that is not a shift start."""
    day = start.astimezone(timezone.utc).date()
    if window(scn, day)[0] < start:
        day += timedelta(days=1)
    end = start + timedelta(days=days + 2)
    runs = W.expand(defn, start, end)
    shifts = set(shift_occurrences(scn, start, days + 2))
    others = [t for t in runs if t not in shifts]
    bad = []
    for d in range(days):
        lo, hi = window(scn, day + timedelta(days=d))
        if hi <= lo:
            bad.append(f"the window on {day + timedelta(days=d)} is empty (scenario error)")
        elif not any(lo <= t <= hi for t in others):
            bad.append(f"no run besides the shift rule falls between {lo.strftime('%H:%M')} and {hi.strftime('%H:%M')} UTC on the morning after {day + timedelta(days=d)}")
    return bad


# ── the scenario sheet (/home/elastic/cortex-ops/scenarios.md) ───────────────

def _fmt_shift(h: int) -> str:
    return f"{h:02d}:00"


def scenario_sheet(scn: dict) -> str:
    """The sheet the learner reads: the desk's zone and shift starts and three needs worded as outcomes, never as trigger patterns
    (28 section 4). The variant's id is not printed; the numbers are the variant."""
    feed = scn["feed_utc"]
    return f"""# Cortex fraud desk: how Tina is run

Time zone: {scn['tz']}. The desk starts a shift at {', '.join(_fmt_shift(h) for h in scn['shift_hours'])} (local time) and opens its day at {scn['desk_open_local']} local time.

## What the desk needs

1. **No change reaches an analyst unchecked.** Whenever Tina is changed, the change is checked against the canary questions, and the result is tied to that change's id.
2. **Overnight drift is caught before the desk opens.** The sanctions feed lands at {feed} UTC every day. Anything it does to Tina's answers must be found at least 15 minutes after it lands and at least 15 minutes before the desk opens at {scn['desk_open_local']} local time. Work in one time zone.
3. **Every answer that used a SAR search is audited within a minute.** One record per such answer, naming the round and the conversation.

## What you are given

The canary workflow `cortex-canary-run`, the audit workflow `cortex-answer-audit`, and the deploy script `/home/elastic/cortex-ops/cortex-deploy.sh`.
"""


# ── the deploy script (/home/elastic/cortex-ops/cortex-deploy.sh) ────────────

BLOCK_OPEN = "# >>> AFTER DEPLOY: add what should run after a deploy; $CHANGE_ID is this deploy's change id >>>"
BLOCK_CLOSE = "# <<< AFTER DEPLOY <<<"

DEPLOY_SCRIPT = f"""#!/bin/bash
# Cortex's deploy script: applies one change to Tina through the Agent Builder API and records it in cortex-change-log.
# Usage: cortex-deploy.sh --change-id <id> --change-file <file.json>
# The file holds {{"kind": "agent" | "tool", "id": "<object id>", "body": {{...the fields to PUT...}}}}.
set -euo pipefail
source "${{HOME}}/env"
CHANGE_ID=""; CHANGE_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --change-id) CHANGE_ID="$2"; shift 2 ;;
    --change-file) CHANGE_FILE="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$CHANGE_ID" && -f "$CHANGE_FILE" ]] || {{ echo "usage: cortex-deploy.sh --change-id <id> --change-file <file.json>" >&2; exit 2; }}
KIND=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kind"])' "$CHANGE_FILE")
OBJ=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$CHANGE_FILE")
BODY=$(python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["body"]))' "$CHANGE_FILE")
curl -sS -f -X PUT "$KIBANA_URL/api/agent_builder/${{KIND}}s/$OBJ" -H "Authorization: ApiKey $ES_API_KEY" -H "kbn-xsrf: true" -H "Content-Type: application/json" -d "$BODY" > /dev/null
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
curl -sS -f -X POST "$ES_URL/cortex-change-log/_doc?refresh=wait_for" -H "Authorization: ApiKey $ES_API_KEY" -H "Content-Type: application/json" \\
  -d "{{\\"at\\": \\"$NOW\\", \\"kind\\": \\"deploy\\", \\"object\\": \\"$OBJ\\", \\"change_id\\": \\"$CHANGE_ID\\", \\"actor\\": \\"cortex-ops\\"}}" > /dev/null
echo "deployed $OBJ as $CHANGE_ID"
{BLOCK_OPEN}
{BLOCK_CLOSE}
"""


def _split_block(text: str) -> tuple[str, str, str] | None:
    if BLOCK_OPEN not in text or BLOCK_CLOSE not in text:
        return None
    head, rest = text.split(BLOCK_OPEN, 1)
    block, tail = rest.split(BLOCK_CLOSE, 1)
    return head, block, tail


def check_deploy_script(text: str, canary_workflow: str = "cortex-canary-run") -> list[str]:
    """N1 (ARTIFACT): the script outside the marked block is the provided one (nothing wired before the deploy step), and the block
    starts the canary workflow through the workflow run endpoint with the deploy's change id as the `change_id` input."""
    parts = _split_block(text)
    if parts is None:
        return ["the marked block was removed from cortex-deploy.sh"]
    head, block, tail = parts
    want_head, _, want_tail = _split_block(DEPLOY_SCRIPT)
    bad = []
    if head != want_head or tail != want_tail:
        bad.append("cortex-deploy.sh was changed outside the marked block: the call belongs at the end, after the deploy step")
    code = "\n".join(line for line in block.splitlines() if not line.strip().startswith("#"))
    if canary_workflow not in code:
        bad.append(f"the block does not start {canary_workflow}")
    elif "/run" not in code and "workflow" not in code:
        bad.append("the block does not call the workflow run endpoint")
    if "$CHANGE_ID" not in code and "${CHANGE_ID}" not in code:
        bad.append("the block does not pass the deploy's change id ($CHANGE_ID)")
    return bad
