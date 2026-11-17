"""ara_ops: the three variants, DST-correct shift expansion, the N2 window, and the wrong-solution fixtures (28 section 4 acceptance 1)."""
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ara_ops as O  # noqa: E402

START = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def wf(*triggers):
    return {"id": "cortex-canary-run", "triggers": [{"type": "manual"}] + list(triggers)}


def rule(tz, hours, minute=0):
    return {"type": "scheduled", "with": {"rrule": {"freq": "DAILY", "interval": 1, "byhour": list(hours), "byminute": [minute], "tzid": tz}}}


def test_the_three_variants_differ_and_are_picked_by_participant():
    assert {O.scenario(p)["id"] for p in ("a", "b", "c", "d", "e", "f", "g", "h")} == {"O1", "O2", "O3"}
    assert O.scenario("a") == O.scenario("a")


def test_window_never_contains_a_shift_start_in_any_variant_even_across_dst():
    for scn in O.VARIANTS:
        for start in (START, datetime(2026, 3, 5, 12, tzinfo=timezone.utc), datetime(2026, 10, 25, 12, tzinfo=timezone.utc)):
            shifts = O.shift_occurrences(scn, start, 7)
            assert len(shifts) == 21
            for d in range(7):
                lo, hi = O.window(scn, start.date() + timedelta(days=d))
                assert hi - lo >= timedelta(minutes=30), (scn["id"], start, d)
                assert not any(lo <= t <= hi for t in shifts)


def test_a_correct_shift_rule_passes_in_one_rule_or_three():
    for scn in O.VARIANTS:
        one = wf(rule(scn["tz"], scn["shift_hours"]))
        three = wf(*[rule(scn["tz"], [h]) for h in scn["shift_hours"]])
        assert O.check_shift_rule(one, scn, START) == [] == O.check_shift_rule(three, scn, START)


def test_shift_rule_wrong_solutions_fail_with_a_message():
    o1 = O.VARIANTS[0]
    assert O.check_shift_rule(wf(rule("UTC", o1["shift_hours"])), o1, START)             # no tzid: occurrences in UTC
    o2 = O.VARIANTS[1]
    assert O.check_shift_rule(wf(rule(o2["tz"], o2["shift_hours"])), o1, START)          # another variant's rule
    interval = wf(rule(o1["tz"], o1["shift_hours"]), {"type": "scheduled", "with": {"every": "1m"}})
    msgs = O.check_shift_rule(interval, o1, START)
    assert any("interval trigger" in m for m in msgs)
    assert O.check_shift_rule(wf(), o1, START)                                            # run by hand only


def test_n2_needs_a_run_in_the_window_besides_the_shift_rule():
    for scn in O.VARIANTS:
        shift = rule(scn["tz"], scn["shift_hours"])
        assert O.check_n2(wf(shift), scn, START), "the shift rule alone must miss the window"
        lo, hi = O.window(scn, START.date() + timedelta(days=1))
        mid = (lo + (hi - lo) / 2).astimezone(timezone.utc)
        ok = wf(shift, rule("UTC", [mid.hour], mid.minute))
        assert O.check_n2(ok, scn, START) == [], scn["id"]


def test_n2_at_a_time_inside_the_window_in_utc_but_wrong_in_the_desks_zone_fails():
    o1 = O.VARIANTS[0]
    lo, hi = O.window(o1, START.date() + timedelta(days=1))
    mid = lo + (hi - lo) / 2
    wrong_zone = wf(rule(o1["tz"], [mid.hour], mid.minute))  # the UTC time read as local: five hours off
    assert O.check_n2(wrong_zone, o1, START)


def test_patterns_key():
    assert O.PATTERNS == {"N1": "ad_hoc", "N2": "scheduled", "N3": "per_response"}


import subprocess  # noqa: E402


def test_scenario_sheet_states_the_numbers_and_never_names_a_pattern():
    for scn in O.VARIANTS:
        sheet = O.scenario_sheet(scn)
        assert scn["tz"] in sheet and scn["feed_utc"] in sheet and scn["desk_open_local"] in sheet
        assert all(f"{h:02d}:00" in sheet for h in scn["shift_hours"]) and scn["id"] not in sheet
        low = sheet.lower()
        assert not any(w in low for w in ("ad hoc", "ad_hoc", "per_response", "per-response", "rrule", "cron", "scheduled trigger", "post-execution"))
    assert O.scenario_sheet(O.VARIANTS[0]) != O.scenario_sheet(O.VARIANTS[1])


def test_deploy_script_is_valid_bash_and_ends_with_an_empty_marked_block(tmp_path):
    f = tmp_path / "deploy.sh"
    f.write_text(O.DEPLOY_SCRIPT)
    assert subprocess.run(["bash", "-n", str(f)]).returncode == 0
    assert O.DEPLOY_SCRIPT.rstrip().endswith(O.BLOCK_CLOSE) and O.check_deploy_script(O.DEPLOY_SCRIPT)


def test_deploy_script_runs_against_stub_curl_and_logs_the_change(tmp_path):
    import json, os
    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "calls.txt"
    (bindir / "curl").write_text(f'#!/bin/bash\necho "$@" >> {log}\n')
    (bindir / "curl").chmod(0o755)
    (tmp_path / "env").write_text("KIBANA_URL=http://k\nES_URL=http://e\nES_API_KEY=x\n")
    (tmp_path / "chg.json").write_text(json.dumps({"kind": "tool", "id": "cortex.escalate", "body": {"description": "d"}}))
    script = tmp_path / "deploy.sh"
    script.write_text(O.DEPLOY_SCRIPT)
    r = subprocess.run(["bash", str(script), "--change-id", "chg-9", "--change-file", str(tmp_path / "chg.json")],
                       env={"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": str(tmp_path)}, capture_output=True, text=True)
    assert r.returncode == 0 and "deployed cortex.escalate as chg-9" in r.stdout
    calls = log.read_text().splitlines()
    assert "-X PUT http://k/api/agent_builder/tools/cortex.escalate" in calls[0] and "/cortex-change-log/_doc" in calls[1] and "chg-9" in calls[1]
    bad = subprocess.run(["bash", str(script)], env={"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": str(tmp_path)}, capture_output=True, text=True)
    assert bad.returncode == 2


def test_n1_check_accepts_the_call_at_the_end_with_the_change_id_and_names_each_wrong_solution():
    good = O.DEPLOY_SCRIPT.replace(O.BLOCK_CLOSE, 'curl -sS -X POST "$KIBANA_URL/api/workflows/workflow/cortex-canary-run/run" -d "{\\"inputs\\": {\\"change_id\\": \\"$CHANGE_ID\\"}}"\n' + O.BLOCK_CLOSE)
    assert O.check_deploy_script(good) == []
    before = good.replace("set -euo pipefail\n", "set -euo pipefail\ncurl cortex-canary-run \"$CHANGE_ID\"\n").replace('curl -sS -X POST "$KIBANA_URL/api/workflows/workflow/cortex-canary-run/run" -d "{\\"inputs\\": {\\"change_id\\": \\"$CHANGE_ID\\"}}"\n', "")
    msgs = O.check_deploy_script(before)
    assert any("outside the marked block" in m for m in msgs) and any("does not start" in m for m in msgs)
    no_id = O.DEPLOY_SCRIPT.replace(O.BLOCK_CLOSE, 'curl -X POST "$KIBANA_URL/api/workflows/workflow/cortex-canary-run/run"\n' + O.BLOCK_CLOSE)
    assert any("change id" in m for m in O.check_deploy_script(no_id))
    assert any("removed" in m for m in O.check_deploy_script("#!/bin/bash\necho hi\n"))
    commented = O.DEPLOY_SCRIPT.replace(O.BLOCK_CLOSE, "# curl cortex-canary-run $CHANGE_ID\n" + O.BLOCK_CLOSE)
    assert O.check_deploy_script(commented)


def test_allow_extra_keeps_shift_starts_and_permits_the_window_run():
    o1 = O.VARIANTS[0]
    shifts = rule(o1["tz"], o1["shift_hours"])
    window_run = {"type": "scheduled", "with": {"rrule": {"freq": "DAILY", "interval": 1, "tzid": "UTC", "byhour": [9], "byminute": [15]}}}
    both = {"triggers": [{"type": "manual"}] + [t for t in wf(shifts)["triggers"] if t["type"] == "scheduled"] + [window_run]}
    assert O.check_shift_rule(both, o1, START)                                   # Build 1: exactly the shift starts
    assert O.check_shift_rule(both, o1, START, allow_extra=True) == []           # Build 2: extras allowed
    assert O.check_shift_rule(wf(rule(o1["tz"], [6])), o1, START, allow_extra=True)  # a missing shift start still fails
