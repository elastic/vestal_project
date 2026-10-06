<!--
TEMPLATE: private/calibration.md, one shape for every ARA track (alignment N5, 2026-10-06).
Delete this block before use. Keep every section heading; write "None." where one does not apply.
Implements 18 §1.7 (reference score, gate, margin per MEASURED gate) with P15 (shared validator on
held-out and dev sets), P16 (separability for threshold-graded sets), P17 (reference from
learner-visible inputs), P18 (naive score and participant id behind every number), P19 (naive must
fail), P20 (numbers from aggregated REFERENCE, NAIVE-GATE and CALIB lines), ruling 5 (See it
yourself) and the lane 3 Defend control. Migrating: put this structure on top and move the old body,
verbatim, under "## History"; nothing is deleted.
-->
# <N.N> calibration record

Recorded <YYYY-MM-DD> on `v2-managed-elastic-serverless`, assets ref `<tag or sha>`, with models and endpoints as provisioned (<env var names and ids>).

## Runs

| Run | Participant id | Date | What it measured |
|---|---|---|---|
| <track test or calibration run> | `<id>` | <YYYY-MM-DD> | <which Builds, reference and naive> |

## T9 validation

`python3 lib/kit/validate_heldout.py --track <dir> --assets <vestal>` gives <n> FAIL and <n> WARN. <One line per WARN, with why it can't false-pass.>

## Provisioning

Cold start <n> min over <n> runs (`<participant ids>`); `EXPECTED_MIN=<n>` in the status writer.

## Build <n>: <title>

**Reference solution.** <What it does and where its code is. Learner-visible inputs only (P17).>

**Naive baseline.** <The start state or the obvious wrong approach.>

| Configuration | Held-out <metric> | Dev <metric> | Source |
|---|---|---|---|
| <reference> | <score> | <score> | `<participant id>` |
| <naive> | <score> | <score> | `<participant id>` |

| Gate (`thresholds.json` key) | Value | Rule |
|---|---|---|
| `<key>` | <value> | Reference <score> minus a margin of <margin>. Naive <score> is below the gate. |

**Naive must fail.** <The naive state the solve builds, and the fail-message line the last track test printed (P19).>

**Known misses in the reference.** <Items the reference fails, and why.>

## See it yourself

<Per Build: the cell and its measured output, with a line that it shows no held-out item (P14); or one line saying why this Build has no cell.>

## Defend

| Question | Reachable outcomes on reference-adjacent work | Source |
|---|---|---|
| q1 | <at least two, with the numbers that produce each> | `<participant id>` |

## Open

<Anything not yet measured live, with what would close it.>

## History

<Dated entries, oldest first. Earlier calibration text moves here verbatim.>
