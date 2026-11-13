<!-- DRAFT. One template per seed; the 01 setup writes the sandbox's one to /home/elastic/cortex-eval/change-request.md.
     {braces} fill from private/heldout/5-c-provided-runs.json and thresholds.json at setup. Numbers marked NEEDS_CAL are
     not known until calibration (07 2.8 item 2): do not ship a draft with a guessed figure. The text states the change, the
     objects it touched, the staging result and the rate card. It never names the hole (that is the learner's finding). -->

# Change request CR-{n}: {title}

**From:** the Cortex platform team. **Status:** applied in staging. **Asked of you:** sign off for production.

## Rate card

Cost is priced on Cortex's rate card, the same one as Lab 5.4: fresh input $2.00, cached input $0.20, output $8.00 per million tokens (made-up figures in realistic proportion). `ara-eval.py compare` prints cost per 1,000 questions on this card. A token count is not a cost.

---

## S1 template: {title} = Faster citations

SAR-citation questions send Tina whole narratives. We added `cortex-sar-passages-fast`, a copy of the SAR narratives cut into short passages (each carries the narrative's `case_type`, `risk_tier` and subject fields), and a search tool `cortex.sar_passages` over it. Tina now holds `cortex.sar_passages` in place of `cortex.sar_search`, which is still defined but no longer on her tool list. Both analyst roles (`cortex-analyst-l1`, `cortex-investigator`) were granted `read` on the new index so the tool works.

**What it improves.** Cost per 1,000 questions on test set `v1`, over the {n_s1} SAR-citation questions.

| Run | Cost per 1,000 (SAR-citation) | Cached share |
|---|---|---|
| baseline | ${baseline} | {baseline_cached} |
| staging | ${staging} ({change_pct} percent) | {staging_cached} |

**Threshold to keep the gain:** a cut of at least {threshold_pct_abs} percent against the baseline. **Category limit:** no category's routing accuracy down more than {category_drop_limit_points} points.

---

## S2 template: {title} = Follow the citation

Regulators' replies cite pages in a regulator library we copied under a second approved source, `{second_prefix}`. For Tina to read them, `cortex-read-page` now admits any `https://` URL. The workflow still has one `http` step.

**What it improves.** The share of regulation questions in `v1` whose `cortex.read_page` call fetched the page the question cites (`page_fetch_ok`, recomputed from the workflow's `http` step by the check).

| Run | Page-fetch share (regulation, {n_s2} questions) |
|---|---|
| baseline | {baseline_points} percent |
| staging | {staging_points} percent (+{change_points} points) |

**Approved sources.** `{first_prefix}` and `{second_prefix}`. **Threshold to keep the gain:** a rise of at least {threshold_points} points. **Category limit:** as above.

---

## S3 template: {title} = Cut tokens

To lower cost per question we changed `cortex.sar_search` to return the first {s3_excerpt_chars} characters of the top {s3_excerpt_rows} matches instead of whole narratives and, in the same tidy-up, removed a block of fixed text from Tina's instructions (agent `tina-compliance`, `configuration.instructions`). Nothing else changed.

**What it improves.** Cost per 1,000 questions on `v1`, over every agent-level question ({n_agent}).

| Run | Cost per 1,000 | Cached share |
|---|---|---|
| baseline | ${baseline} | {baseline_cached} |
| staging | ${staging} ({change_pct} percent) | {staging_cached} |

**Threshold to keep the gain:** a cut of at least {threshold_pct_abs} percent. **Category limit:** as above.

---

## What we need from you (all seeds)

Decide whether this ships. Re-measure on `v1` with the harness, label `secured`, and record your decision through the decision recorder. Your numbers decide, not ours.
