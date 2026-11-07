# r/AskHistorians

Config: `mining/configs/askhistorians.yaml`. Full run: `mining/run_askhistorians_full.sbatch`.

## Verification tier

`vetted`: mods grant flair after reviewing a user's answers; it is not a credential check.

## Flair vocabulary

From the pilot (334 posts, 673 flaired comments excluding AutoModerator, 71 distinct flairs):

- **Almost all flairs are free-text topic areas** (e.g. `Early Modern England`, `Norse Society and Culture`),
  often prefixed with a role: `Moderator | ...`, `Mod Emeritus | ...`. A keyword list can't cover the topic
  flairs a full year will contain.
- Role-only flairs: `Moderator | Quality Contributor` (100 comments), `Verified` (83), `Quality Contributor` (17),
  `Inactive Flair` (5).
- Non-expert flairs: `FAQ Finder` (19, links old answers), `Interesting Inquirer` (10, given for good questions),
  `Automated Contributor` (2, a bot).
- **`Verified` is the AMA guest flair**: 83 comments from 3 accounts (Christopher_F_Jones 42, JapanHistProf 39,
  kmondschein 2), 80 of them in 2 AMA threads, answering commenters rather than the OP.
- **Template IDs are unusable**: they are shared across unrelated flairs (e.g. one id covers both `Verified` and
  `Law & Public Welfare`).

Most common flairs:

| author_flair_text | comments | > 1000 chars |
|---|---:|---:|
| Moderator \| Quality Contributor | 100 | 6 |
| Verified | 83 | 44 |
| Moderator \| Shipbuilding and Logistics \| British Navy 1770-1830 | 37 | 10 |
| Moderator \| History of Education \| Abortion | 31 | 8 |
| Moderator \| Medieval Warfare (Logistics and Equipment) | 30 | 21 |
| Moderator \| 20th Century Royal Navy | 26 | 16 |
| Modern France \| Social, Cultural, and Colonial | 25 | 13 |
| Moderator \| Dueling \| Modern Warfare & Small Arms | 22 | 3 |
| Moderator \| Taiping Heavenly Kingdom \| Qing Empire | 20 | 6 |
| FAQ Finder | 19 | 4 |
| Law & Public Welfare | 18 | 10 |
| Quality Contributor | 17 | 5 |
| Comparative Religion | 15 | 11 |

## Expert rule and rationale

Approved by Shoji, 2026-11-05:

- `match_any_flair: true` with `exclude_flair_keywords: ["Interesting Inquirer", "FAQ Finder", "Automated Contributor"]`.
  Inactive Flair, Mod Emeritus and Verified count (inclusive policy, Brihi 2026-10).
- `skip_distinguished: ["moderator"]`: all 142 mod-distinguished flaired comments were mod actions, none answers
  (removal notices, "repost to Short Answers" redirects, "we're letting this stand, but..." caveat notes, AMA
  etiquette reminders). 67 of them are 1000+ chars, so length alone can't filter them. Without the skip,
  183/334 posts are expert at min 100; with it, 92.
- `min_body_chars: 100`: non-distinguished flaired comments have p10/p25/median/p75/p90 = 111/304/568/1698/3248 chars.
  Under 100 are non-answers ("Sorry, I'm really not well informed!"); 100-1000 holds real answers (a 991-char
  archival answer, score 1042) and substantive "see my other answer" pointers. Expert posts at min 100/300/1000:
  92/81/70.
- Thresholds: `min_selftext_chars: 0` (questions are often title-only), `min_num_comments: 2` (AutoModerator
  stickies a comment on every thread).
- Known leak: one undistinguished mod removal notice (2237 chars, "unfortunately we have had to remove your
  question") still qualifies. Rare.

## Numbers

| Run | Where | Result |
|---|---|---|
| Pilot (`--max-scanned 1000`, 2026-11-05, default window 2025-10-30 -> 2026-10-30) | `/scratch2/sawatana/mining/pilot/AskHistorians/2025-10-30_2026-10-30/posts.jsonl` (6.2 MB) | 1000 scanned -> 334 passed. 10.8 min, 346 requests, 1 retry. Mined under the placeholder rule (86 expert); **92 expert** under the final rule. Posts span 2025-10-30 -> 2025-11-07. |
| **Full run** (job 6784399, done 2026-11-06, commit f4208c7) | `/scratch2/sawatana/mining/full/AskHistorians/2025-09-23_2026-09-23/posts.jsonl` (92 MB), log `/scratch2/sawatana/logs/mine-askhistorians-full-6784399.out` | 41,033 scanned -> 13,831 passed -> **4,088 expert** (29.6% of passed, 10.0% of scanned). 446.7 min, 14,278 requests, 31 retries. All records rule `f889a51521`, tier `vetted`; 0 posts with unexpanded "more" nodes. After downstream filters: 3,787 expert posts excluding megathreads (318 megathread posts, 301 of them expert); selected expert comment top-level in 3,202/4,088 (78.3%); **both filters: 3,081**. |

## Downstream filters to apply

- **Drop megathread posts by `link_flair_text`**: AMA, Digest, SASQ, FFA, Best Of, META (10 of 334 pilot posts;
  318 of 13,831 full-run posts, 301 of them expert).
  They are not a poster asking a question: AMA expert comments answer other commenters, and the Sunday Digest is
  mod link roundups ("* /u/x answered [..]", flaired `Moderator | Quality Contributor`). Not skipped at mining
  time (decided 2026-11-05).
- **Consider requiring a top-level expert comment**: the selected expert comment is top-level (`depth == 0`) in
  79/92 pilot expert posts (3,202/4,088 = 78.3% in the full run); 83/92 pilot posts have *some* qualifying
  top-level comment. See NOTES_mining.md,
  "Re-flagging downstream".
- Removed comments: AskHistorians mods remove heavily; `[removed]` bodies are kept in `comments` (only flaired,
  long-enough bodies can be selected as expert, so they never are).
