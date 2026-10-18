#!/usr/bin/env python3
"""
Mine one subreddit from Arctic Shift into resumable JSONL.

Every post that passes the basic thresholds is written, one per line, with its
full comment tree embedded as a flat list (parent_id + depth per comment) and
an is_expert flag from the expert rule in the config. Filter downstream.

Output (run dir = <out-root>/<subreddit>/<after>_<before>/):
    posts.jsonl       one post per line
    checkpoint.json   cursor + counters, replaced atomically (tmp + rename)
    run_config.json   resolved config for this run
    mine.log          appended log

Resume = rerun the same command with the same --after/--before. On startup a
truncated final JSONL line is dropped and already-written post_ids are skipped,
so a kill at any point loses at most the post in flight.

Examples:
    python collectors/mine_subreddit.py --config collectors/configs/tax.yaml \\
        --max-expert-posts 10 --time-budget 25
    python collectors/mine_subreddit.py --config collectors/configs/tax.yaml \\
        --after 2025-09-23 --before 2026-09-23
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

logger = logging.getLogger("mine")

POST_FIELDS = (
    "id", "subreddit", "title", "selftext", "author", "author_flair_text",
    "author_flair_template_id", "score", "upvote_ratio", "num_comments", "created_utc", "permalink", "url",
    "link_flair_text", "over_18", "is_self", "edited", "removed_by_category",
    "retrieved_on", "_meta",
)
COMMENT_FIELDS = (
    "id", "parent_id", "author", "author_flair_text", "author_flair_template_id",
    "author_flair_css_class", "body", "score", "created_utc", "is_submitter", "distinguished", "stickied",
    "edited", "permalink", "retrieved_on", "_meta",
)


class StopRequested(Exception):
    pass


class FatalAPIError(Exception):
    pass


# ---------------------------------------------------------------------------
# Config / window
# ---------------------------------------------------------------------------


def subtract_months(d: datetime, months: int) -> datetime:
    y, m = divmod(d.month - 1 - months, 12)
    year, month = d.year + y, m + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return d.replace(year=year, month=month, day=day)


def parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def resolve_window(cfg: dict, cli_after: str | None, cli_before: str | None) -> tuple[datetime, datetime]:
    win = cfg.get("window", {})
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    before_s = cli_before or win.get("before")
    before = parse_date(before_s) if before_s else today - timedelta(days=win.get("end_days_before_now", 5))
    after_s = cli_after or win.get("after")
    after = parse_date(after_s) if after_s else subtract_months(before, win.get("months", 12))
    if after >= before:
        sys.exit(f"Empty window: after {after:%Y-%m-%d} >= before {before:%Y-%m-%d}")
    if before > today - timedelta(days=2):
        logger.warning("Window ends %s, less than 2 days ago; scores/comment counts may not have settled",
                       f"{before:%Y-%m-%d}")
    return after, before


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class ArcticShift:
    def __init__(self, http_cfg: dict, stop_flag: dict):
        self.base = http_cfg["base_url"].rstrip("/")
        self.cfg = http_cfg
        self.stop_flag = stop_flag
        self.session = requests.Session()
        self.session.headers["User-Agent"] = http_cfg["user_agent"]
        self.last_request = 0.0
        self.n_requests = 0
        self.n_retries = 0

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.stop_flag["stop"]:
                raise StopRequested(self.stop_flag["reason"])
            if self.stop_flag["deadline"] and time.monotonic() >= self.stop_flag["deadline"]:
                raise StopRequested("time_budget")
            time.sleep(min(1.0, end - time.monotonic()))

    def get(self, path: str, **params: Any) -> list:
        for attempt in range(self.cfg["max_retries"] + 1):
            wait = self.cfg["request_interval_s"] - (time.monotonic() - self.last_request)
            if wait > 0:
                self._sleep(wait)
            self.last_request = time.monotonic()
            self.n_requests += 1
            retry_after = None
            try:
                resp = self.session.get(f"{self.base}{path}", params=params, timeout=self.cfg["timeout_s"])
                # Arctic Shift returns 422 {"error":"Timeout. Maybe slow down a bit"} for
                # server-side timeouts, so 422 is retried like 429/5xx.
                if resp.status_code in (422, 429) or resp.status_code >= 500:
                    problem = f"HTTP {resp.status_code}"
                    retry_after = _retry_after_seconds(resp)
                elif resp.status_code >= 400:
                    raise FatalAPIError(f"HTTP {resp.status_code} for {path} {params}: {resp.text[:300]}")
                else:
                    body = resp.json()
                    if isinstance(body, dict) and body.get("data") is not None:
                        return body["data"]
                    problem = f"API error body: {str(body)[:200]}"
            except (requests.ConnectionError, requests.Timeout, ValueError) as e:
                problem = f"{type(e).__name__}: {e}"
            if attempt == self.cfg["max_retries"]:
                raise FatalAPIError(f"Giving up on {path} {params} after {attempt + 1} tries: {problem}")
            backoff = min(self.cfg["backoff_max_s"], self.cfg["backoff_base_s"] * 2 ** attempt)
            backoff = max(backoff * random.uniform(0.8, 1.2), retry_after or 0)
            self.n_retries += 1
            logger.warning("%s on %s; retry %d/%d in %.0fs", problem, path, attempt + 1,
                           self.cfg["max_retries"], backoff)
            self._sleep(backoff)
        raise AssertionError("unreachable")


def _retry_after_seconds(resp: requests.Response) -> float | None:
    for header in ("Retry-After", "x-ratelimit-reset"):
        try:
            return float(resp.headers[header])
        except (KeyError, ValueError):
            continue
    return None


# ---------------------------------------------------------------------------
# Comment tree
# ---------------------------------------------------------------------------


def _flatten(nodes: list, comments: dict[str, dict], mores: list[dict]) -> None:
    for node in nodes:
        data = node.get("data") or {}
        if node.get("kind") == "more":
            mores.append(data)
            continue
        comments[data["id"]] = data
        replies = data.get("replies")
        if isinstance(replies, dict):
            _flatten(replies.get("data", {}).get("children", []), comments, mores)


def fetch_comments(api: ArcticShift, post_id: str) -> tuple[list[dict], int]:
    """Return (flat comment list, number of unexpanded 'more' nodes left)."""
    link_id = f"t3_{post_id}"
    limit = api.cfg["tree_limit"]
    raw: dict[str, dict] = {}
    mores: list[dict] = []
    _flatten(api.get("/api/comments/tree", link_id=link_id, limit=limit), raw, mores)

    # A "more" node's children list only its direct children, so expand by
    # fetching the full subtree under the collapsed parent (or, for top-level
    # "more" nodes, under each listed child).
    expanded_roots: set[str] = set()
    for _ in range(api.cfg["max_expand_rounds"]):
        if not mores:
            break
        roots: list[str] = []
        for more in mores:
            parent = more.get("parent_id", "")
            if parent.startswith("t1_"):
                roots.append(parent)
            else:
                roots.extend(f"t1_{c}" for c in more.get("children", []) if c not in raw)
        roots = [r for r in dict.fromkeys(roots) if r not in expanded_roots]
        mores = []
        for root in roots:
            expanded_roots.add(root)
            _flatten(api.get("/api/comments/tree", link_id=link_id, parent_id=root, limit=limit), raw, mores)
        if not roots:
            break
    if mores:
        logger.warning("Post %s: %d 'more' nodes left unexpanded after %d rounds",
                       post_id, len(mores), api.cfg["max_expand_rounds"])

    comments = [{k: c.get(k) for k in COMMENT_FIELDS} for c in raw.values()]
    by_id = {c["id"]: c for c in comments}

    depths: dict[str, int | None] = {}

    def depth(c: dict) -> int | None:
        # Iterative walk up parent_ids; None = orphan (parent missing from archive).
        chain = []
        while c["id"] not in depths:
            chain.append(c["id"])
            parent = c.get("parent_id") or ""
            if parent.startswith("t3_"):
                base = -1
                break
            c = by_id.get(parent[3:])
            if c is None or len(chain) > len(by_id):
                base = None
                break
        else:
            base = depths[c["id"]]
        for i, cid in enumerate(reversed(chain)):
            depths[cid] = None if base is None else base + 1 + i
        return depths[chain[0]] if chain else depths[c["id"]]

    for c in comments:
        c["depth"] = depth(c)
    comments.sort(key=lambda c: (c.get("created_utc") or 0, c["id"]))
    return comments, len(mores)


# ---------------------------------------------------------------------------
# Thresholds / expert rule
# ---------------------------------------------------------------------------


def passes_thresholds(post: dict, th: dict) -> bool:
    selftext = post.get("selftext") or ""
    if selftext in th["skip_selftext"] or len(selftext) < th["min_selftext_chars"]:
        return False
    return (post.get("num_comments") or 0) >= th["min_num_comments"] and (post.get("score") or 0) >= th["min_score"]


def comment_qualifies(c: dict, rule: dict) -> bool:
    flair = c.get("author_flair_text") or ""
    keywords = rule["flair_keywords"]
    if not rule["case_sensitive"]:
        flair, keywords = flair.lower(), [k.lower() for k in keywords]
    return any(k in flair for k in keywords) and len(c.get("body") or "") > rule["min_body_chars"]


def select_expert(comments: list[dict], rule: dict) -> str | None:
    ranked = sorted(comments, key=lambda c: (-(c.get("score") or 0), c.get("created_utc") or 0))
    if rule["scope"] == "top_scored":
        ranked = ranked[:1]
    elif rule["scope"] != "any":
        sys.exit(f"Unknown expert.scope {rule['scope']!r}; use 'any' or 'top_scored'")
    for c in ranked:
        if c["is_expert"]:
            return c["id"]
    return None


# ---------------------------------------------------------------------------
# Output / checkpoint
# ---------------------------------------------------------------------------


def atomic_write_json(path: Path, value: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(value, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def repair_and_load_output(path: Path) -> dict[str, dict]:
    """Drop a truncated final line, then return {post_id: {is_expert, created_utc}}."""
    existing: dict[str, dict] = {}
    if not path.exists():
        return existing
    with open(path, "rb+") as f:
        data = f.read()
        lines = data.split(b"\n")
        # Complete file ends with "\n", so the last split element is b"".
        tail = lines.pop()
        keep = len(data) - len(tail)
        if lines:
            try:
                json.loads(lines[-1])
            except json.JSONDecodeError:
                bad = lines.pop()
                keep -= len(bad) + 1
                tail = bad + b"\n" + tail
        if tail:
            logger.warning("Dropping truncated final line of %s (%d bytes)", path, len(tail))
            f.truncate(keep)
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            sys.exit(f"{path}:{i} is corrupt mid-file ({e}); not touching it. Inspect manually.")
        existing[rec["post_id"]] = {"is_expert": rec["is_expert"], "created_utc": rec["created_utc"]}
    return existing


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Mine a subreddit from Arctic Shift into resumable JSONL")
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--after", help="YYYY-MM-DD (UTC, inclusive); overrides config")
    ap.add_argument("--before", help="YYYY-MM-DD (UTC, exclusive); overrides config")
    ap.add_argument("--out-root", type=Path, default=Path("/scratch2/sawatana/mining"))
    ap.add_argument("--max-expert-posts", type=int, help="Stop once this many expert posts are in the output (cumulative)")
    ap.add_argument("--max-scanned", type=int, help="Stop once this many posts are scanned (cumulative)")
    ap.add_argument("--time-budget", type=float, help="Stop after this many minutes (this invocation)")
    ap.add_argument("--tree-limit", type=int, help="Override http.tree_limit (testing 'more' expansion)")
    ap.add_argument("--pause-every", type=int,
                    help="Pause after every N posts scanned, 0 = never (default: http.pause_every, else 500)")
    ap.add_argument("--pause-seconds", type=float,
                    help="Length of each pause (default: http.pause_seconds, else 30)")
    args = ap.parse_args()

    cfg = yaml.safe_load(args.config.read_text())
    sub, th, rule, http_cfg = cfg["subreddit"], cfg["thresholds"], cfg["expert"], cfg["http"]
    if args.tree_limit:
        http_cfg["tree_limit"] = args.tree_limit
    # Resolved into http_cfg so run_config.json records the values actually used.
    http_cfg["pause_every"] = args.pause_every if args.pause_every is not None else http_cfg.get("pause_every", 500)
    http_cfg["pause_seconds"] = (args.pause_seconds if args.pause_seconds is not None
                                 else http_cfg.get("pause_seconds", 30))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        handlers=[logging.StreamHandler(sys.stderr)])
    after_dt, before_dt = resolve_window(cfg, args.after, args.before)
    after_s, before_s = f"{after_dt:%Y-%m-%d}", f"{before_dt:%Y-%m-%d}"
    after_ts, before_ts = int(after_dt.timestamp()), int(before_dt.timestamp())

    run_dir = args.out_root / sub / f"{after_s}_{before_s}"
    run_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(run_dir / "mine.log")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(fh)

    out_path, ckpt_path = run_dir / "posts.jsonl", run_dir / "checkpoint.json"
    rule_version = hashlib.sha1(json.dumps(rule, sort_keys=True).encode()).hexdigest()[:10]
    atomic_write_json(run_dir / "run_config.json",
                      {"config_file": str(args.config.resolve()), "config": cfg, "after": after_s,
                       "before": before_s, "expert_rule_version": rule_version})

    logger.info("=" * 60)
    logger.info("r/%s  window %s -> %s (UTC, before exclusive)", sub, after_s, before_s)
    logger.info("Run dir: %s", run_dir)
    logger.info("Caps: max_expert_posts=%s max_scanned=%s time_budget=%s min",
                args.max_expert_posts, args.max_scanned, args.time_budget)
    logger.info("Pause: %ss every %s posts scanned", http_cfg["pause_seconds"], http_cfg["pause_every"])

    # Resume: output file is the source of truth for what's written;
    # checkpoint only tells us where the scan cursor was.
    existing = repair_and_load_output(out_path)
    counters = {"scanned": 0, "passed": 0, "expert": 0}
    cursor_ts, done_at_cursor = after_ts, set()
    if ckpt_path.exists():
        ck = json.loads(ckpt_path.read_text())
        if (ck["subreddit"], ck["after"], ck["before"]) != (sub, after_s, before_s):
            sys.exit(f"Checkpoint {ckpt_path} is for a different run: {ck['subreddit']} {ck['after']}->{ck['before']}")
        cursor_ts, done_at_cursor, counters = ck["cursor_ts"], set(ck["done_ids_at_cursor"]), ck["counters"]
        covered = [v for k, v in existing.items()
                   if v["created_utc"] < cursor_ts or (v["created_utc"] == cursor_ts and k in done_at_cursor)]
        if len(covered) != counters["passed"] or sum(v["is_expert"] for v in covered) != counters["expert"]:
            logger.warning("Checkpoint counters (passed=%d expert=%d) disagree with output up to cursor "
                           "(passed=%d expert=%d); using output-derived values",
                           counters["passed"], counters["expert"], len(covered), sum(v["is_expert"] for v in covered))
            counters["passed"], counters["expert"] = len(covered), sum(v["is_expert"] for v in covered)
        logger.info("Resuming from cursor %s: %d posts already in output, counters %s",
                    datetime.fromtimestamp(cursor_ts, timezone.utc).isoformat(), len(existing), counters)
    elif existing:
        logger.info("No checkpoint but %d posts in output; rescanning window, skipping known post_ids", len(existing))
    start_counters = dict(counters)

    stop = {"stop": False, "reason": None, "deadline": None}

    def on_signal(signum, _frame):
        stop["stop"], stop["reason"] = True, f"signal {signal.Signals(signum).name}"
        logger.warning("Received %s; finishing current post then exiting", stop["reason"])

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    api = ArcticShift(http_cfg, stop)
    t0 = time.monotonic()
    deadline = t0 + args.time_budget * 60 if args.time_budget else None
    stop["deadline"] = deadline

    def save_checkpoint() -> None:
        atomic_write_json(ckpt_path, {
            "subreddit": sub, "after": after_s, "before": before_s, "cursor_ts": cursor_ts,
            "done_ids_at_cursor": sorted(done_at_cursor), "counters": counters,
            "expert_rule_version": rule_version, "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    def cap_reason() -> str | None:
        if stop["stop"]:
            return stop["reason"]
        if args.max_expert_posts is not None and counters["expert"] >= args.max_expert_posts:
            return "max_expert_posts"
        if args.max_scanned is not None and counters["scanned"] >= args.max_scanned:
            return "max_scanned"
        if deadline and time.monotonic() >= deadline:
            return "time_budget"
        return None

    reason, exit_code = None, 0
    out = open(out_path, "a")
    try:
        while not (reason := cap_reason()):
            # `after` is exclusive in Arctic Shift, so ask for cursor-1 and skip what's done.
            page = api.get("/api/posts/search", subreddit=sub, sort="asc", after=cursor_ts - 1,
                           before=before_ts, limit=100)
            if not page:
                reason = "window_complete"
                break
            page.sort(key=lambda p: (p["created_utc"], p["id"]))
            new = [p for p in page if p["created_utc"] > cursor_ts
                   or (p["created_utc"] == cursor_ts and p["id"] not in done_at_cursor)]
            if not new:
                if len(page) < 100:
                    reason = "window_complete"
                    break
                logger.warning("100+ posts share created_utc=%d; skipping ahead one second", cursor_ts)
                cursor_ts, done_at_cursor = cursor_ts + 1, set()
                continue

            for post in new:
                if (reason := cap_reason()):
                    break
                pid, ts = post["id"], post["created_utc"]
                if ts != cursor_ts:
                    cursor_ts, done_at_cursor = ts, set()

                # Counters only move once a post is fully handled, so a kill
                # mid-post leaves checkpoint counters consistent with the cursor.
                if passes_thresholds(post, th):
                    if pid in existing:
                        is_expert = existing[pid]["is_expert"]
                    else:
                        comments, n_unexpanded = fetch_comments(api, pid)
                        for c in comments:
                            c["is_expert"] = comment_qualifies(c, rule)
                        expert_id = select_expert(comments, rule)
                        is_expert = expert_id is not None
                        rec = {"post_id": pid, **{k: post.get(k) for k in POST_FIELDS if k != "id"},
                               "is_expert": is_expert, "expert_comment_id": expert_id,
                               "expert_rule_version": rule_version, "n_comments_fetched": len(comments),
                               "n_more_unexpanded": n_unexpanded, "comments": comments}
                        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        out.flush()
                        os.fsync(out.fileno())
                        existing[pid] = {"is_expert": is_expert, "created_utc": ts}
                    counters["passed"] += 1
                    counters["expert"] += is_expert
                counters["scanned"] += 1
                done_at_cursor.add(pid)
                if counters["scanned"] % 25 == 0 or pid in existing:
                    save_checkpoint()
                if counters["scanned"] % 100 == 0:
                    log_progress(counters, t0, cursor_ts, api)
                pause_every = http_cfg["pause_every"]
                if pause_every and counters["scanned"] % pause_every == 0 and not cap_reason():
                    save_checkpoint()
                    logger.info("Pausing %ss after %d posts scanned", http_cfg["pause_seconds"], counters["scanned"])
                    api._sleep(http_cfg["pause_seconds"])
            save_checkpoint()
    except StopRequested as e:
        # _sleep raises with the reason as the message; stop["reason"] is unset for time_budget.
        reason = stop["reason"] or str(e)
    except FatalAPIError as e:
        logger.error("%s", e)
        reason, exit_code = "api_error", 2
    finally:
        out.close()
        save_checkpoint()

    log_summary(reason, counters, start_counters, t0, api, out_path, sub, after_s, before_s, args.config)
    return exit_code


def _rates(c: dict) -> str:
    pr = f"{c['expert'] / c['passed']:.1%}" if c["passed"] else "n/a"
    sr = f"{c['expert'] / c['scanned']:.2%}" if c["scanned"] else "n/a"
    return (f"scanned={c['scanned']} passed_thresholds={c['passed']} expert={c['expert']} "
            f"| expert/passed={pr} expert/scanned={sr}")


def log_progress(counters: dict, t0: float, cursor_ts: int, api: ArcticShift) -> None:
    # Requests/retries are for this invocation (not carried across resumes).
    logger.info("[%s, %.1f min] %s | requests=%d retries=%d",
                datetime.fromtimestamp(cursor_ts, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                (time.monotonic() - t0) / 60, _rates(counters), api.n_requests, api.n_retries)


def log_summary(reason, counters, start, t0, api, out_path, sub, after_s, before_s, config) -> None:
    session = {k: counters[k] - start[k] for k in counters}
    logger.info("=" * 60)
    logger.info("Stopped: %s after %.1f min, %d requests (%d retries)",
                reason, (time.monotonic() - t0) / 60, api.n_requests, api.n_retries)
    logger.info("This run:   %s", _rates(session))
    logger.info("Cumulative: %s", _rates(counters))
    logger.info("Output: %s", out_path)
    if reason != "window_complete":
        logger.info("Resume with: python collectors/mine_subreddit.py --config %s --after %s --before %s [caps]",
                    config, after_s, before_s)


if __name__ == "__main__":
    sys.exit(main())
