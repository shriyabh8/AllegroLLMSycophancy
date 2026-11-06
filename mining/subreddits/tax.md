# r/tax

Config: `mining/configs/tax.yaml`. Full run: `mining/run_tax_full.sbatch`.

## Verification tier

`self_asserted`: users set their own flair; nobody checks credentials.

## Flair vocabulary

From all comments in the 297 rate-check posts (2025-09-23 -> 2025-10-06):

| author_flair_text | comments | posts |
|---|---|---|
| CPA - US | 211 | 76 |
| Tax Preparer - US | 135 | 84 |
| EA - US | 107 | 62 |
| Taxpayer - US | 82 | 38 |
| US CPA & Attorney (tax) | 79 | 48 |
| Tax Lawyer - US | 26 | 13 |
| 🤡 | 9 | 7 |
| EA | 4 | 4 |
| JD/CPA - US | 4 | 4 |
| Attorney - US | 3 | 2 |
| CPA - US / Former IRS Revenue Agent | 2 | 2 |
| Enrolled Agent - US | 2 | 2 |
| Tax Attorney - US | 2 | 1 |
| TaxAide Volunteer - US | 2 | 2 |
| Tax Preparer - | 1 | 1 |
| RTRP - US | 1 | 1 |
| LL.M. - Tax | 1 | 1 |
| CPA - US [Tax Gremlin] | 1 | 1 |

- Flair is user-editable free text, and **template IDs are unreliable**, so matching on text is the only option.
  Verified via `/api/comments/ids`: template `1d11f540-3c16-11e3-af63-12313d21c4ee` (the Tax Preparer template)
  also carries `EA` (3), `EA - US` (12), `Enrolled Agent - US` (1) and `🤡` (9). `EA - US` also appears under its
  own template `65a9cec6-...` (95). `Tax Lawyer - US` has a template of its own (`36ed76c0-...`).
- Substring false positive seen outside the sample: `Future EA` matches `EA` (2026-03-01 smoke test).

## Expert rule and rationale

Current rule `ba9c68bf61` (2026-10-18): case-sensitive substring match on any of CPA, EA, Tax Professional,
Accountant, Attorney, Tax Attorney, CFP, Tax Preparer, Tax Lawyer, Enrolled Agent, RTRP, LL.M., TaxAide;
body > 100 chars; `scope: any` (highest-scored qualifying comment at any depth).

- Started from the old repo's `pipeline/screen_cases.py:get_expert_responded_posts` rule (rule `2743884bfd`:
  CPA, EA, Tax Professional, Accountant, Attorney, Tax Attorney, CFP).
- Brihi (2026-10): Tax Preparer counts as expert; lean inclusive on expert flair. Added Tax Preparer, Tax Lawyer,
  Enrolled Agent (spelled out, so "EA" doesn't match it), RTRP, LL.M., TaxAide.
- Re-applying the inclusive rule to the 297 rate-check posts (file left untouched): **118 -> 164 expert (+46)**.
  New posts by selected expert flair: Tax Preparer 40, Tax Lawyer 5, TaxAide 1. Newly qualifying comments:
  Tax Preparer 110, Tax Lawyer 23, Enrolled Agent 2, RTRP 1, LL.M. 1, TaxAide 1.
- Min length sensitivity (old rule): lowering `min_body_chars` from 100 to 20 would flip 21 of 179 non-expert
  posts (~12%) to expert. Nobody has reviewed whether those short answers are real corrections.

## Numbers

| Run | Where | Result |
|---|---|---|
| Pilot (`--max-expert-posts 10`, 2026-09-28) | `/project2/robinjia_875/sawatana/pilot/tax_pilot_20260928.jsonl` | 20 posts (238 KB), 10 expert. Posts from 2025-09-23 only. |
| Rate check (`--max-scanned 1000`, 2026-09-28) | `/project2/robinjia_875/sawatana/pilot/tax_ratecheck_20260928.jsonl` (copy of `/scratch2/sawatana/mining/rate-check/tax/2025-09-23_2026-09-23/posts.jsonl`; checkpoint and log only there) | 1000 scanned -> 297 passed -> 118 expert (old rule; 164 under the current rule). 5.6 min, 308 requests, 0 retries. |
| **Full run** (job 6501422, done 2026-10-18) | `/scratch2/sawatana/mining/full/tax/2025-09-23_2026-09-23/posts.jsonl` (122 MB), log `/scratch2/sawatana/logs/mine-tax-full-6501422.out` | 31,172 scanned -> 8,444 passed -> **4,356 expert** (51.6% of passed, 14.0% of scanned). 342 min, 8,862 requests, 102 retries (all HTTP 422). All records rule `ba9c68bf61`; 0 posts with unexpanded "more" nodes. |

- Pilot and rate-check files predate `author_flair_template_id` and are under the old rule `2743884bfd`.
- All r/tax files predate `verification_tier`, so no record has the field; the tier is `self_asserted` (this file / config).
- The rate check covered only 2025-09-23 -> 2025-10-06 (off-season). Its extrapolation (~26k posts, ~2.5 h) was
  a lower bound; the full year was 31k posts and 5.7 h.

## Downstream filters to apply

- **Removed posts:** 773/8,444 full-run posts (33/297 in the rate check) have `removed_by_category` set (removed on
  Reddit after archiving; selftext still present). Decide whether to keep them.
- **Non-top-level expert comments:** with `scope: any`, the selected expert comment is top-level (`depth == 0`) in
  3,274/4,356 (75.2%) of full-run expert posts; the rest reply to another comment, not the OP. Consider requiring
  `depth == 0` (see NOTES_mining.md, "Re-flagging downstream").
- **Flair false positives:** check selected-expert flairs for non-credentials matched by substring (e.g. `Future EA`).
