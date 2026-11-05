#!/usr/bin/env python3
"""Stage 3 — triage. Sonnet clusters items into *events*, scores risk-on/off potential,
assigns theme threads, and writes the regime note.

Semantic clustering is mandatory, not an optimization: string dedup cannot match
`日米協調介入` to "joint US-Japan intervention", so a cross-language feed set collapses only
if a model does the matching (SPEC decision 13).

The relevance floor is hard. Zero deep dives is a valid outcome, and manufacturing
significance on a quiet day is the standard failure mode of daily briefs.

Usage: triage.py [--date YYYY-MM-DD] [--hours 48] [--floor 55] [--max-deep 3] [--dry-run]
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import db as dbm
import market
import prefilter

MODEL = "sonnet"
MAX_ITEMS = 5000         # everything in the window; prefilter.py owns the real budget
FLOOR = 55               # risk_score below this never gets a dive
MAX_DEEP = 3

SYSTEM = """\
You are the triage stage of a pre-open macro brief for a Japanese equities trader.

His book: long **small-cap, high-beta Japanese equities** (東証グロース250 / TSE Growth), hedged
with **short Nikkei 225 micro futures**. He reads the brief at 07:00 JST, before the 09:00 open.

Your job is to turn a raw multi-language feed dump into a ranked list of *events*.

## What counts

Score each event on **risk-on/risk-off potential for Japanese equities today** — NOT on general
newsworthiness. A cabinet reshuffle may lead every newspaper and score 20. A single line in a
BOJ 主な意見 about the terminal rate may be buried and score 75.

High score: policy-rate signals (BOJ/Fed), FX at intervention thresholds, US tape moves that
set the Tokyo open, semis/SOX shocks, liquidity and margin conditions, credit events, tariffs
or export controls hitting Japanese supply chains, systemic geopolitics.

Low score: single-company earnings without sector read-through, routine 決算速報 and レーティング
日報, product launches, retail-investor commentary, opinion columns with no new fact.

## Rules

1. **Cluster across languages and sources.** `日米協調介入` and "joint US-Japan intervention"
   are ONE event. Merge every item covering the same underlying event into one entry, listing
   every contributing item id.
2. **Use only the item ids given to you.** Never invent an id, a headline, or an event that is
   not in the input.
3. **Score honestly. Most days have nothing above 55.** Do not inflate to fill a quota. If the
   feed is genuinely quiet, return events that all score below the floor — that is a correct
   and useful answer.
4. **Never state a market number that is not in the market_snapshot given to you.** The regime
   note must cite only those figures.
5. `title_en` is required and must be genuinely informative — not a translation of a vague
   Japanese headline. `title_ja` is the original Japanese where one exists, else null.
6. **Threads are long-lived themes**, not per-day topics: `yen-defense`, `boj-normalization`,
   `fed-path`, `semis-cycle`, `us-tariffs`, `china-slowdown`. Reuse an existing slug from
   `open_threads` whenever the event belongs to that theme; only mint a new slug for a
   genuinely new theme.
7. `query_ja` / `query_en` are the search queries a later research stage will use to pull
   articles on this event. Make them specific enough to retrieve the event and nothing else.

## Output

Return **only** a JSON object, no prose and no code fence:

{
  "regime_note": "2-3 sentences on the tape the trader is walking into. Cite only numbers from
                  market_snapshot. Say what the setup is, not what to do about it.",
  "events": [
    {
      "title_en": "...",
      "title_ja": "..." | null,
      "risk_score": 0-100,
      "risk_direction": "risk-on" | "risk-off" | "ambiguous",
      "why": "one line: the transmission channel that makes this matter to JP equities",
      "item_ids": [12, 45],
      "thread_slug": "yen-defense",
      "thread_name": "Yen defense",
      "query_ja": "...",
      "query_en": "..."
    }
  ]
}

Return at most 25 events, sorted by risk_score descending. Every item worth mentioning at all
should belong to some event; items that are pure noise may be dropped.
"""


def gather_items(db, hours):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    rows = db.execute("""
        SELECT i.id, i.title, i.source, i.lang, i.published_at, i.summary, f.name feed, f.kind
        FROM items i JOIN feeds f ON f.id = i.feed_id
        WHERE COALESCE(i.published_at, i.fetched_at) >= ? AND f.enabled = 1
        ORDER BY CASE f.kind WHEN 'jp-official' THEN 0 WHEN 'us-official' THEN 1
                             WHEN 'jp-analysis' THEN 2 ELSE 3 END,
                 COALESCE(i.published_at, i.fetched_at) DESC
        LIMIT ?""", (cutoff, MAX_ITEMS)).fetchall()
    return [{"id": r["id"], "title": r["title"], "source": r["source"] or r["feed"],
             "kind": r["kind"], "lang": r["lang"], "published": r["published_at"],
             "summary": (r["summary"] or "")[:300] or None} for r in rows]


def open_threads(db, days=45):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    return [{"slug": r["slug"], "name": r["name"], "summary": r["summary"]}
            for r in db.execute(
                "SELECT slug,name,summary FROM threads WHERE COALESCE(last_seen_at,created_at)>=? "
                "ORDER BY last_seen_at DESC LIMIT 20", (since,))]


def run_claude(prompt, system, model=MODEL, timeout=1500):
    """Triage is pure reasoning over supplied text — no tools, so none are allowed."""
    p = subprocess.run(
        ["claude", "-p", prompt, "--model", model,
         "--append-system-prompt", system, "--allowedTools", ""],
        capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"claude exited {p.returncode}: {(p.stderr or p.stdout)[-600:]}")
    return p.stdout


def triage_with_fallback(build_prompt, budget, timeout):
    """Try the full payload; on timeout or unparseable output, retry smaller.

    Latency on this box is not a function of prompt size alone — every Claude agent here shares
    one OAuth credential and one rate-limit pool, so an identical call can take two minutes or
    twenty depending on what else is running. A brief that degrades to fewer items still beats a
    brief that does not exist, so each attempt narrows the payload rather than giving up.
    """
    attempts = [(budget, timeout), (max(60, budget // 2), timeout), (40, timeout)]
    last = None
    for i, (n, t) in enumerate(attempts, 1):
        prompt, kept = build_prompt(n)
        try:
            print(f"triage attempt {i}: {len(kept)} items, {len(prompt)//1024}KB, {t}s cap",
                  flush=True)
            return extract_json(run_claude(prompt, SYSTEM, timeout=t)), kept
        except (subprocess.TimeoutExpired, ValueError, json.JSONDecodeError,
                RuntimeError) as e:
            last = e
            print(f"  attempt {i} failed: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
    raise RuntimeError(f"all {len(attempts)} triage attempts failed; last: "
                       f"{type(last).__name__}: {str(last)[:300]}")


def extract_json(raw):
    """Models sometimes fence the JSON or prepend a line despite instructions."""
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if m:
        raw = m.group(1)
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e <= s:
        raise ValueError(f"no JSON object in output: {raw[:400]!r}")
    return json.loads(raw[s:e + 1])


def upsert_thread(db, slug, name, now):
    if not slug:
        return None
    slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")[:48] or None
    if not slug:
        return None
    db.execute("INSERT INTO threads(slug,name,created_at,last_seen_at) VALUES(?,?,?,?) "
               "ON CONFLICT(slug) DO UPDATE SET last_seen_at=excluded.last_seen_at",
               (slug, name or slug, now, now))
    return db.execute("SELECT id FROM threads WHERE slug=?", (slug,)).fetchone()["id"]


def persist(db, brief_id, result, valid_ids, floor, max_deep, force=False):
    now = dbm.now_utc()
    # Re-runs are idempotent, but events CASCADE to dives -- so a casual `triage.py` re-run
    # after the dives have landed would silently destroy half an hour of Opus work.
    done = db.execute(
        "SELECT COUNT(*) c FROM dives d JOIN events e ON e.id=d.event_id "
        "WHERE e.brief_id=? AND d.status='done'", (brief_id,)).fetchone()["c"]
    if done and not force:
        raise SystemExit(f"refusing to re-triage: {done} completed dive(s) on this brief would "
                         f"be deleted by CASCADE. Pass --force if that is what you want.")
    db.execute("DELETE FROM events WHERE brief_id=?", (brief_id,))
    events = [e for e in result.get("events", []) if e.get("title_en")]
    events.sort(key=lambda e: -int(e.get("risk_score") or 0))

    deep = 0
    for rank, e in enumerate(events[:25]):
        score = max(0, min(100, int(e.get("risk_score") or 0)))
        tier = "thin"
        if score >= floor and deep < max_deep:
            tier, deep = "deep", deep + 1
        tid = upsert_thread(db, e.get("thread_slug"), e.get("thread_name"), now)
        cur = db.execute(
            "INSERT INTO events(brief_id,title_en,title_ja,risk_score,risk_direction,tier,rank,"
            "why,thread_id,query_ja,query_en) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (brief_id, e["title_en"], e.get("title_ja"), score,
             e.get("risk_direction"), tier, rank, e.get("why"), tid,
             e.get("query_ja"), e.get("query_en")))
        for iid in e.get("item_ids") or []:
            if iid in valid_ids:      # the model must not be able to invent an id
                db.execute("INSERT OR IGNORE INTO event_items(event_id,item_id) VALUES(?,?)",
                           (cur.lastrowid, iid))
    db.execute("UPDATE briefs SET status='triaged', regime_note=?, error=NULL WHERE id=?",
               (result.get("regime_note"), brief_id))
    db.commit()
    return len(events[:25]), deep


def main():
    def opt(flag, default, cast=str):
        return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default

    date_jst, hours = opt("--date", None), opt("--hours", 48, int)
    floor, max_deep = opt("--floor", FLOOR, int), opt("--max-deep", MAX_DEEP, int)

    db = dbm.connect()
    brief_id = dbm.get_or_create_brief(db, date_jst)
    raw_items = gather_items(db, hours)
    if not raw_items:
        dbm.fail_brief(db, brief_id, "no items in window — check fetch stage")
        sys.exit("triage: no items in window")
    snap = market.load(db, brief_id)
    wl = dbm.watchlist_dict(db)
    threads = open_threads(db)

    def build_prompt(budget):
        items, dropped = prefilter.apply(raw_items, budget=budget)
        payload = {
            "generated_at_jst": datetime.now(dbm.JST).isoformat(timespec="seconds"),
            "market_snapshot": snap,
            "watchlist": wl,
            "open_threads": threads,
            "items": items,
        }
        return ("Triage today's feed. Input:\n\n"
                + json.dumps(payload, ensure_ascii=False, indent=1)), items

    budget = opt("--budget", prefilter.BUDGET, int)
    if "--dry-run" in sys.argv:
        print(build_prompt(budget)[0])
        return

    try:
        result, items = triage_with_fallback(build_prompt, budget,
                                            opt("--timeout", 1500, int))
    except Exception as e:
        dbm.fail_brief(db, brief_id, f"triage failed: {type(e).__name__}: {e}")
        raise

    n, deep = persist(db, brief_id, result, {i["id"] for i in items}, floor, max_deep,
                      force="--force" in sys.argv)
    print(f"brief={brief_id} items={len(items)} events={n} deep={deep} floor={floor}")
    for r in db.execute("SELECT risk_score,risk_direction,tier,title_en FROM events "
                        "WHERE brief_id=? ORDER BY rank LIMIT 8", (brief_id,)):
        print(f"  [{r['risk_score']:3}] {r['tier']:5} {r['risk_direction'] or '-':10} "
              f"{r['title_en'][:70]}")
    db.close()


if __name__ == "__main__":
    main()
