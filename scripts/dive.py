#!/usr/bin/env python3
"""Stage 4 — deep dives. One fresh Opus session per event, loading the macro-dive skill.

Parallel with incremental publish (SPEC decision 11). This is what fixes the DST trap: in
winter there are only ~45 minutes between the US cash close (06:00 JST) and 07:00 JST, so
three sequential 30-minute dives cannot fit. Run concurrently, wall-clock is the slowest
single dive; each row goes to `status='researching'` before its session starts, so the
dashboard shows work in flight rather than an empty page.

Usage: dive.py [--date YYYY-MM-DD] [--event ID] [--model opus] [--timeout 2100] [--jobs 3]
"""
import concurrent.futures as cf
import json
import re
import subprocess
import sys
from pathlib import Path

import bundle
import db as dbm

SKILL = Path(__file__).resolve().parent.parent / ".claude/skills/macro-dive/SKILL.md"
MODEL = "opus"
TIMEOUT = 2100      # 35 min: the skill's budget is 30, plus slack for the final write-up
JOBS = 3

FM_KEYS = ("verdict", "confidence", "horizon", "thread", "jp_equity_direction",
           "high_beta_note", "falsifier")

# The skill's output contract. Checked rather than trusted: the first pipeline dive silently
# omitted "Transmission — US equities", and a missing section is invisible on a page that
# renders whatever it is given.
REQUIRED_SECTIONS = (
    "What happened", "Why now, why this form", "Who benefits", "Second-order effects",
    "Transmission — Japanese equities", "Transmission — US equities",
    "Policy path — BOJ and Fed", "Market-implied odds", "Thread context", "Verdict",
    "What would falsify this", "Watchlist impact",
)
WORD_MIN, WORD_MAX = 700, 1900   # tolerance around the skill's 900-1,600 budget


def audit(fm, body):
    """-> list of contract violations, stored on the dive so drift is visible, not silent."""
    problems = []
    have = set(re.findall(r"^##\s+(.+?)\s*$", body, re.M))
    for s in REQUIRED_SECTIONS:
        if s not in have:
            problems.append(f"missing section: {s}")
    for extra in sorted(have - set(REQUIRED_SECTIONS)):
        problems.append(f"unexpected section: {extra}")
    for k in ("verdict", "confidence", "falsifier"):
        if not fm.get(k):
            problems.append(f"missing frontmatter: {k}")
    if fm.get("verdict") not in (None, "risk-on", "risk-off", "ambiguous"):
        problems.append(f"invalid verdict: {fm['verdict']}")
    n = len(body.split())
    if not WORD_MIN <= n <= WORD_MAX:
        problems.append(f"length {n}w outside {WORD_MIN}-{WORD_MAX}")
    if "news.google.com" in body:
        problems.append("cites a Google News redirect instead of the publisher URL")
    return problems


def parse_frontmatter(text):
    """Split the YAML frontmatter the skill emits from the markdown body.

    Deliberately not a YAML parser: the contract is flat `key: value` lines, and a real parser
    would happily accept structures the pipeline cannot store.

    Tolerant of two things the skill forbids but that a model still does occasionally: a preamble
    line above the frontmatter, and wrapping it in a ```yaml fence. Losing a whole 25-minute dive
    to a stray "Research complete —" would be a bad trade, so the parser finds the block rather
    than requiring it at byte zero.
    """
    text = text.strip()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        # locate the first plausible frontmatter block, skipping a preamble and/or a ```yaml fence
        m = re.search(r"(?:^|\n)(?:```(?:yaml)?[ \t]*\n)?---[ \t]*\n(.*?)\n---[ \t]*\n"
                      r"(?:```[ \t]*\n)?(.*)$", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip().strip("\"'")
            if k in FM_KEYS and v:
                fm[k] = v
    return fm, m.group(2).strip()


def extract_sources(body):
    """Markdown links, deduped in order. Google redirects are excluded: they are unresolvable
    tokens and the skill forbids citing them, so any that appear are a defect to surface."""
    urls, seen = [], set()
    for u in re.findall(r"\((https?://[^)\s]+)\)", body):
        u = u.rstrip(".,;")
        if u not in seen and "news.google.com" not in u:
            seen.add(u)
            urls.append(u)
    return urls


PROMPT = """Analyze this single macro event for the 07:00 JST pre-open brief.

Follow the macro-dive method and output format exactly. The input bundle below contains every
market number you are permitted to state without fetching and citing a source; `source_headlines`
lists the clustered coverage behind this event, and `thread_prior_entries` is what you concluded
on this same theme previously — say what has changed.

INPUT BUNDLE:
{bundle}
"""


def run_one(event_id, model, timeout, skill_text):
    """Own connection per thread: sqlite3 objects are not shareable across threads."""
    db = dbm.connect()
    try:
        ev = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        brief_id = ev["brief_id"]
        b = bundle.build(db, brief_id, event=ev)
        db.execute("DELETE FROM dives WHERE event_id=?", (event_id,))
        cur = db.execute("INSERT INTO dives(event_id,status,model,started_at) "
                         "VALUES(?,'researching',?,?)", (event_id, model, dbm.now_utc()))
        dive_id = cur.lastrowid
        db.commit()          # publish 'researching' before the long call, not after
    except Exception as e:
        db.close()
        return event_id, f"setup failed: {type(e).__name__}: {e}"

    prompt = PROMPT.format(bundle=json.dumps(b, ensure_ascii=False, indent=1))
    try:
        p = subprocess.run(
            ["claude", "-p", prompt, "--model", model,
             "--append-system-prompt", skill_text,
             "--allowedTools", "WebSearch,WebFetch"],
            capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise RuntimeError(f"claude exited {p.returncode}: {(p.stderr or p.stdout)[-600:]}")
        out = p.stdout.strip()
        if not out:
            raise RuntimeError("empty output")
        fm, body = parse_frontmatter(out)
        if not body:
            raise RuntimeError(f"no body parsed from {len(out)}B output")
        # A dive that breaks the contract still publishes -- the analysis is usually sound even
        # when a section is missing -- but the violation is recorded so it cannot pass unnoticed.
        problems = audit(fm, body)
        db.execute(
            "UPDATE dives SET status='done', finished_at=?, verdict=?, confidence=?, horizon=?,"
            " jp_equity_direction=?, high_beta_note=?, falsifier=?, body_md=?, sources_json=?,"
            " error=? WHERE id=?",
            (dbm.now_utc(), fm.get("verdict"), fm.get("confidence"), fm.get("horizon"),
             fm.get("jp_equity_direction"), fm.get("high_beta_note"), fm.get("falsifier"),
             body, json.dumps(extract_sources(body)),
             ("contract: " + "; ".join(problems)) if problems else None, dive_id))
        db.commit()
        note = f" [{len(problems)} contract issue(s): {'; '.join(problems)}]" if problems else ""
        return event_id, f"ok {len(body.split())}w verdict={fm.get('verdict')}{note}"
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"[:900]
        db.execute("UPDATE dives SET status='error', finished_at=?, error=? WHERE id=?",
                   (dbm.now_utc(), msg, dive_id))
        db.commit()
        return event_id, f"FAIL {msg}"
    finally:
        db.close()


def main():
    def opt(flag, default, cast=str):
        return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default

    date_jst = opt("--date", None)
    model, timeout, jobs = opt("--model", MODEL), opt("--timeout", TIMEOUT, int), opt("--jobs", JOBS, int)
    skill_text = SKILL.read_text()

    db = dbm.connect()
    if "--event" in sys.argv:
        # Take the brief from the event, never from the clock. Calling get_or_create_brief() here
        # meant a manual dive run after 15:00 UTC (= past midnight JST) minted an empty brief for
        # the next day and marked it 'published' -- so the dashboard showed tomorrow's blank page
        # saying "nothing cleared the relevance floor", which is a lie, not an empty result.
        ids = [opt("--event", None, int)]
        row = db.execute("SELECT brief_id FROM events WHERE id=?", (ids[0],)).fetchone()
        if not row:
            db.close()
            sys.exit(f"no such event: {ids[0]}")
        brief_id = row["brief_id"]
    else:
        brief_id = dbm.get_or_create_brief(db, date_jst)
        ids = [r["id"] for r in db.execute(
            "SELECT id FROM events WHERE brief_id=? AND tier='deep' ORDER BY rank",
            (brief_id,))]
    db.close()

    single = "--event" in sys.argv
    if not ids:
        print("no deep events — quiet day, which is a valid outcome")
        with dbm.connect() as d:
            d.execute("UPDATE briefs SET status='published', published_at=? WHERE id=?",
                      (dbm.now_utc(), brief_id))
            d.commit()
        return

    print(f"diving {len(ids)} event(s) on {model}, {jobs} at a time")
    fails = 0
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(run_one, i, model, timeout, skill_text): i for i in ids}
        for fut in cf.as_completed(futs):
            eid, msg = fut.result()
            print(f"  event {eid}: {msg}")
            fails += msg.startswith("FAIL") or msg.startswith("setup")

    if not single:
        with dbm.connect() as d:
            # A partial brief still publishes; the failed dive shows its error on the dashboard.
            d.execute("UPDATE briefs SET status='published', published_at=? WHERE id=?",
                      (dbm.now_utc(), brief_id))
            d.commit()
    if fails:
        print(f"{fails}/{len(ids)} dives failed", file=sys.stderr)


if __name__ == "__main__":
    main()
