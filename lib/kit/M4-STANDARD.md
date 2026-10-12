# M4 to M6 track standard: seed (draft for Joe; Jeff reviews the parts that touch 02, 03, 09)

Started 2026-10-11 from `alignment-matrix.md` section 4 and Draft 0.1 (`m2-fixes/docs/standards/`). A rule here is enforced by the named tool where one exists; the rest are review items. Align by default: a track departs only with a written reason in its QA record.

## Carried from M1 to M3 (enforced today)

| Rule | Enforced by |
|---|---|
| Brief is one page: problem with a real capture, concepts, Decision rule matching the Defend truth table, done numbers from `thresholds.json`, Check | `brief/page.py check`, `align_lint page` |
| Brief gate and solve are the kit files; launcher, provision head, wait block and src lock are the kit blocks; `STEP_TOTAL` equals the step calls; `EXPECTED_MIN` measured | `align_lint gate/launcher/provision/wait/srclock` |
| Track limit = sum of challenge limits + 1800 (labs), + 3600 (capstones); generous X6 limits; Brief 3600 | `align_lint track` |
| Shared grader (N3), 50 s deadline, R-P8: a failed remote call is retried, then no grade, never credited or dropped | `ara_grade.py`, review |
| R-ANS: accepted answers never in a learner-readable file; grades root-only | review, answer-hygiene scan (kit item 4) |
| Every graded number in `thresholds.json`; the page and assignment quote it | review |
| Defend: `defend.py`, `"shuffle": "seed"`, one wrong choice and two wrong reasons per variant, two reachable outcomes, 09 section 7a guidance from the second showing | `align_lint questions`, solve gate PF-DEFEND |
| Held-out vs dev disjoint; T9 on what the learner's data will be | `validate_heldout.py` (+ track plugin) |
| Solve gates: each spec'd wrong solution fails with its message; ERR trap prints PF-FAIL | solve scripts, review |
| Wait text: typical figure plus "but it can take longer" | review |
| No em-dash, no model or vendor names in learner text | `ara-lint.sh` |

## Added for Agent Builder tracks (M4 on)

| Rule | Enforced by |
|---|---|
| Every graded conversation pins `connector_id` (`ARA_AB_CONNECTOR_ID`) and runs as `tina-runtime`, never the admin key | `m4_lint connector/identity`; `AB.converse` refuses without a connector |
| No grading check reads `response.message`; routes and structured literals only | `m4_lint message` |
| Internal platform tools are filtered from routes (`agent_builder.INTERNAL_TOOLS`) | lib, unit tests |
| Question-set gates are k of n from `calibration.md`: reference minimum over at least 5 runs, wrong maximum over at least 3; if no k separates, change the questions | calibration copy (`CALIBRATE=1` in the solves) |
| Each BEHAVIOR gate names the model property it relies on, so a model swap re-measures it | `calibration.md` section |
| Custom tool ids `cortex.<name>`; agents, workflows, indices hyphenated | `m4_lint ids` |
| Start manifest named in the 01 setup; every object a check reads is in the manifest chain or built by the Builds | `m4_lint manifest`; `ara-ab-apply.py --check` (second apply is a no-op) |
| Model ids only on a line marked `# ARA_MODEL` in the env block | `m4_lint model` |
| `ARA_ASSETS_TAG` is an `m4-*` tag | `m4_lint tag` |
| Checks stay under the 50 s deadline: at most 3 converse calls in flight, BEHAVIOR only after ARTIFACT passes | review, durations in `calibration.md` |
| Preview features labelled where they appear (page section and assignment), never on the title | review |
| Key scoping is taught, not relied on: the learner can read the admin credentials (lead probe dcrnnwcpfbv1), so no grade trusts a learner-writable record | review |

## Open for Joe

- Whether the answer-hygiene scan and a shared PF template (kit items 4 and 6) are required before the first M4 tag or before the module release.
- Whether `m4_lint` folds into `ara-lint.sh` on vestal `tools/ara-authoring` (outside this branch).
