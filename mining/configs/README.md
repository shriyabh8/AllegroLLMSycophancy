# Subreddit mining configs

One YAML per subreddit, consumed by `mining/mine_subreddit.py`.

## Running

```bash
module purge; module load gcc/13.3.0 python/3.11.9   # requests + pyyaml via pip --user
cd /project2/robinjia_875/sawatana/AllegroLLMSycophancy
python mining/mine_subreddit.py --config mining/configs/tax.yaml \
    --after 2025-09-23 --before 2026-09-23 [--max-expert-posts N] [--max-scanned N] [--time-budget MIN]
```

- Output: `<out-root>/<subreddit>/<after>_<before>/posts.jsonl` (default out-root `/scratch2/sawatana/mining`),
  plus `checkpoint.json`, `run_config.json`, `mine.log`.
- **Resume** by rerunning with the same `--after/--before` (pass them explicitly: the default window
  moves daily, and a different window is a different run dir). Truncated final lines are dropped and
  known post_ids skipped, so kill/SIGTERM at any time is safe.
- `--max-expert-posts` and `--max-scanned` are cumulative across resumes; `--time-budget` is minutes
  for this invocation. Every exit logs scanned / passed_thresholds / expert counts and pass rates.
- Exit code 0 on window complete, any cap, or SIGTERM/SIGINT; 2 if the API kept failing after retries
  (just rerun to resume). 422 (Arctic Shift's "Timeout. Maybe slow down a bit"), 429 and 5xx are retried with backoff.
- `--pause-every N --pause-seconds S` (or `http.pause_every` / `http.pause_seconds` in the YAML; defaults 500 / 30)
  sleeps S seconds after every N posts scanned; 0 disables. Each pause is logged, and progress lines include
  `requests=` / `retries=` for the current invocation, so throttling shows up as a growing retry count.
- Full r/tax run: `sbatch mining/run_tax_full.sbatch` (from the repo root).

## Record format (one line per post)

Post fields (`post_id`, `title`, `selftext`, `score`, `num_comments`, `created_utc`, `permalink`,
flairs, ...), plus:

- `comments`: flat list of every comment in the tree ("more" nodes expanded), each with `id`,
  `parent_id` (`t3_` = top level, `t1_` = reply), `depth` (0 = top level, null = orphan),
  `author`, `author_flair_text`, `author_flair_template_id`, `body`, `score`, `created_utc`, `is_submitter`, `stickied`, `is_expert`.
  Deleted/removed/short comments are kept; filter downstream.
- `verification_tier`: copied from the config (see below), so records from different subreddits can be
  weighted or filtered by how trustworthy their expert flair is.
- `is_expert`, `expert_comment_id`: result of the config's expert rule at mining time.
  `expert_rule_version` is a hash of the rule, so records mined under different rules are distinguishable.
  Since flair/score/body are stored for every comment, the rule can be re-applied downstream without re-mining.
- `n_comments_fetched`, `n_more_unexpanded` (should be 0; >0 means the tree was not fully expanded).

Every post passing `thresholds` is written, expert or not.

Records mined before `verification_tier` was added have no such field; the subreddit's config gives
its tier. Old output files were not rewritten.

## `verification_tier` (required)

Top-level config key saying how far the sub's expert flair can be trusted. The miner exits if it is
missing or not one of:

| Value | Meaning | Example |
|---|---|---|
| `verified` | Mods check credentials (e.g. proof of license) before granting the flair | r/AskDocs |
| `vetted` | Mods grant the flair after reviewing a user's contributions, without checking credentials | r/AskHistorians |
| `self_asserted` | Users set their own flair; nobody checks it | r/tax |

The tier is per subreddit, not per comment, and does not change `is_expert`. Check the sub's
wiki/rules for how flair is granted before picking one.

## Adding a subreddit

1. Copy `tax.yaml` to `<name>.yaml`, set `subreddit:` (no `r/`) and `verification_tier:`.
2. Set `expert.flair_keywords` inclusively (Brihi, 2026-10): include any flair that indicates professional
   or credentialed experience (e.g. in r/tax, Tax Preparer and TaxAide Volunteer as well as CPA/EA).
   Prefer more data over stricter filtering; every comment's flair is stored, so records can be re-flagged
   downstream with a stricter rule. Look at real flair strings first,
   e.g. `https://arctic-shift.photon-reddit.com/api/comments/search?subreddit=<name>&limit=100`
   and read `author_flair_text`, or run a small `--max-scanned 200` pilot and count flairs.
   Keyword matching is a plain substring (case-sensitive unless `case_sensitive: false`), so short
   keywords over-match (in r/tax, `EA` matches "Future EA").
   Optional `expert` keys (all default off, so existing configs behave as before):
   - `match_any_flair: true`: any non-empty flair matches; `flair_keywords` is ignored. For subs whose
     flairs are free-text topic areas (r/AskHistorians; probably askscience, askphilosophy).
   - `exclude_flair_keywords: [...]`: substrings that disqualify a flair even if it matches (same case rule).
   - `skip_distinguished: ["moderator"]`: comments whose `distinguished` is in the list never qualify
     (mod removal/rule notices are distinguished and written by flaired users).
3. Adjust `thresholds` if the sub's posts are shorter/longer or less active.
4. Pilot with `--max-expert-posts 10 --time-budget 25 --out-root /scratch2/sawatana/mining/pilot`,
   check the logged expert pass rate, then launch the full run.
5. Full runs use the standard window `--after 2025-09-23 --before 2026-09-23` (same as r/tax; PLAN.md).
   Copy `run_tax_full.sbatch` (or `run_askhistorians_full.sbatch`), changing only the job name and `--config`.
6. Create `mining/subreddits/<name>.md` (committed; see `tax.md`, `askhistorians.md`) with the verification tier,
   flair vocabulary summary, expert rule and rationale, pilot/full-run numbers, and downstream filters to apply.

Different subreddits write to different run dirs, so they can be mined in parallel. They all share
the Arctic Shift rate limit, though; keep `request_interval_s` at 0.5+ per process and watch the log
for 429 retries.
