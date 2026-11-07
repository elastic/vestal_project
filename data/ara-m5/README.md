# M5 data (`25` section 8.2)

Generated once by the builder and committed. Setups load these files; none generates data.

## The M3 corpus with identifier fields

`cortex-cases.ndjson` (120) and `cortex-sar-narratives.ndjson` (40), from `scripts/gen_m5_corpus.py` (seed 5) over M3's
`data/cortex-cases/cases.jsonl` and `data/cortex-sar-narratives/bucket_*.jsonl`, which do not change.

| Field | Cases | SAR narratives |
|---|---|---|
| `subject_name` | `customer_name` from `cases.jsonl` | the M3 generator's `subject_name` |
| `subject_account` | the account number the body names; for the 30 cases whose body names none, a new number in the M3 format `NN-NNNNN-N`, used nowhere else | the M3 generator's `subject_account` |
| `subject_tin` | new, `AAA-GG-SSSS`, area 900 to 999 (never issued), unique across both indices | same |

Other fields are the ones M3 indexed (cases: `case_id`, `case_type`, `risk_tier`, `filing_date`, `title`, `body`;
SAR narratives: `sar_id` from `doc_id`, `case_type`, `risk_tier`, `filing_date`, `case_reference`, `body`). Gold
literals and questions are not copied.

Scoping counts the 5.1 access policy relies on: `cortex-cases` has 24 documents per case type and 40 per risk tier
(structuring: 24, of which 16 are `low` or `medium`); `cortex-sar-narratives` has 8 per case type, tiers 10 low,
15 medium, 15 high.

Identifiers inside `body` text stay as M3 wrote them: names and account numbers appear in SAR bodies (40 of 40)
and case bodies (names 119 of 120, accounts 90 of 120). No body holds a TIN-shaped string. FLS hides fields, not
text inside a field, which 5.1 teaches.

## Mappings

`mappings/<index>.json`: `case_type`, `risk_tier`, `subject_*` and the ids are `keyword`; `filing_date` is `date`;
`body` is `semantic_text` on `.jina-embeddings-v5-text-small` (as M3 and M4's `cortex-policies`), with a `body_text`
copy for lexical search. `lib/ara_corpus.py` loads them: `ara-m4-end` without the identifier fields, the 5.1 start
and later with them.
