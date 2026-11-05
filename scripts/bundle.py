#!/usr/bin/env python3
"""The deterministic input bundle for a macro dive.

Every market number the model sees is computed here, in code, so it never has to recall one
(SPEC decision 5). Prediction-market data is fetched with its limitations stated inline, so the
model cannot mistake Kalshi's contract *structure* for an implied probability.

Importable by dive.py; also runnable by hand:
  bundle.py "<ja query>" [--query-en "<en>"] [--out FILE]
"""
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

import db as dbm
import market

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
JST = dbm.JST

PM_NOTE = ("Polymarket serves prices but covers macro thinly. Kalshi lists the right contracts "
           "(including a BOJ decision market) but serves NO prices without an API key. For the "
           "BOJ, use JGB/OIS moves plus analyst consensus and label it a proxy — never present "
           "a proxy as a market price.")


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# Word-boundary patterns. Substring matching is wrong here: bare "fed" matches
# "Obama federally charged" and bare "japan" matches "Will Japan recognize Palestine".
MACRO_PATTERNS = (
    r"\bfed\b", r"\bfomc\b", r"\bboj\b", r"\bbank of japan\b",
    r"interest rate", r"rate (cut|hike|decision)", r"basis points?", r"\bbps\b",
    r"\binflation\b", r"\bcpi\b", r"\brecession\b", r"\bgdp\b", r"unemployment",
    r"\byen\b", r"\busd/?jpy\b", r"\bnikkei\b", r"treasury yield",
)
_MACRO_RE = re.compile("|".join(MACRO_PATTERNS), re.I)

# Rate-path contracts are the ones the brief actually cares about; rank them first.
_PRIORITY_RE = re.compile(r"\bfed\b|\bfomc\b|\bboj\b|interest rate|rate (cut|hike|decision)"
                          r"|basis points?|\bbps\b|\byen\b|\bcpi\b|\binflation\b", re.I)


def polymarket(pattern=_MACRO_RE):
    """Open markets matching macro terms, with current implied odds.

    Polymarket is the only one of the two that serves prices unauthenticated. Coverage of
    macro is thin -- usually a single usable Fed contract. See SOURCES.md section F.
    """
    hits = []
    try:
        # order by volume: the useful rate contracts are high-volume and would otherwise fall
        # outside the scanned window entirely
        for off in (0, 500, 1000, 1500):
            raw = json.loads(get("https://gamma-api.polymarket.com/markets"
                                 f"?limit=500&offset={off}&closed=false"
                                 "&order=volume&ascending=false"))
            if not raw:
                break
            for m in raw:
                q = m.get("question") or ""
                if not pattern.search(q):
                    continue
                try:
                    prices = json.loads(m.get("outcomePrices") or "[]")
                    outcomes = json.loads(m.get("outcomes") or "[]")
                except Exception:
                    prices, outcomes = [], []
                hits.append({
                    "question": m.get("question"),
                    "odds": dict(zip(outcomes, prices)) or None,
                    "volume": m.get("volume"),
                    "end": m.get("endDate"),
                })
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    hits.sort(key=lambda h: (0 if _PRIORITY_RE.search(h["question"] or "") else 1,
                             -float(h.get("volume") or 0)))
    return hits[:12]


_MON = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def _event_date(ticker):
    """Parse the date suffix of a Kalshi event ticker -> date, or None.

    Formats seen: KXFED-26SEP, KXCBDECISIONJAPAN-26SEP17, KXJPCPIYOY-26MAY21.
    Needed because sorting these as strings puts 25DEC (past) before 26SEP (future).
    """
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})?$", ticker or "")
    if not m or m.group(2) not in _MON:
        return None
    return date(2000 + int(m.group(1)), _MON[m.group(2)], int(m.group(3) or 1))


KALSHI = "https://api.elections.kalshi.com/trade-api/v2"


def kalshi_structure(series=("KXFED", "KXCBDECISIONJAPAN", "KXJPCPIYOY")):
    """Nearest-dated outcome STRUCTURE for key policy series.

    Kalshi exposes no prices unauthenticated (0/1000 open markets carry last/bid/volume) and
    the BOJ book is empty. So this yields the shape of the decision, never an implied
    probability. The model must not present any of this as a market price.
    """
    out = {"_warning": "STRUCTURE ONLY -- Kalshi serves no prices without an API key. "
                       "Do not present these outcomes as probabilities."}
    for s in series:
        try:
            evs = json.loads(get(f"{KALSHI}/events?series_ticker={s}&limit=40")).get("events", [])
            if not evs:
                out[s] = {"events": 0}
                continue
            # pick the soonest event still in the future -- NOT string-sorted, which would
            # return a 2025 event as "smallest"
            today = datetime.now(JST).date()
            dated = [(d, e) for e in evs if (d := _event_date(e.get("event_ticker")))]
            future = sorted([p for p in dated if p[0] >= today])
            if not future:
                out[s] = {"events": len(evs), "note": "no future-dated event; series dormant",
                          "latest": max(dated)[1].get("event_ticker") if dated else None}
                continue
            ev = future[0][1]
            ms = json.loads(get(f"{KALSHI}/markets?event_ticker={ev['event_ticker']}&limit=30")
                            ).get("markets", [])
            out[s] = {
                "event": ev.get("event_ticker"),
                "title": ev.get("title"),
                "outcomes": [m.get("yes_sub_title") for m in ms],
                "any_price": any(m.get("last_price") or m.get("yes_bid") for m in ms),
            }
        except Exception as e:
            out[s] = {"error": f"{type(e).__name__}: {e}"}
    return out


def news(query, n=25, lang="ja"):
    """Google News RSS as universal adapter (reaches sources with no RSS).

    Item links are opaque Google redirect tokens that cannot be resolved programmatically, so
    `title` + `source` are what the dive must use to find the publisher's own URL.
    """
    if not query:
        return []
    loc = ("hl=ja&gl=JP&ceid=JP:ja" if lang == "ja" else "hl=en-US&gl=US&ceid=US:en")
    u = ("https://news.google.com/rss/search?q="
         f"{urllib.parse.quote(query)}+when:2d&{loc}")
    try:
        root = ET.fromstring(get(u))
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    items = []
    for it in root.iter("item"):
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "source": (it.findtext("source") or "").strip(),
            "published": (it.findtext("pubDate") or "").strip(),
        })
        if len(items) >= n:
            break
    return items


def watchlist(db=None):
    """Watchlist comes from SQLite (the UI edits it); the JSON file is a seed, not the truth."""
    if db is not None:
        return dbm.watchlist_dict(db)
    with dbm.connect(read_only=True) as d:
        return dbm.watchlist_dict(d)


def event_items(db, event_id):
    """The clustered headlines behind this event, with their real feed URLs."""
    return [{"title": r["title"], "source": r["source"] or r["feed"], "lang": r["lang"],
             "published": r["published_at"], "url": r["url"]}
            for r in db.execute(
                "SELECT i.title,i.source,i.lang,i.published_at,i.url,f.name feed "
                "FROM event_items ei JOIN items i ON i.id=ei.item_id "
                "JOIN feeds f ON f.id=i.feed_id WHERE ei.event_id=? "
                "ORDER BY i.published_at DESC", (event_id,))]


def thread_context(db, thread_id, event_id, n=5):
    """Prior dives on this theme — the continuity that makes 'third signal in six weeks' possible."""
    if not thread_id:
        return []
    return [{"date_jst": r["date_jst"], "event": r["title_en"], "verdict": r["verdict"],
             "confidence": r["confidence"], "high_beta_note": r["high_beta_note"],
             "falsifier": r["falsifier"]}
            for r in db.execute(
                "SELECT b.date_jst,e.title_en,d.verdict,d.confidence,d.high_beta_note,d.falsifier "
                "FROM dives d JOIN events e ON e.id=d.event_id JOIN briefs b ON b.id=e.brief_id "
                "WHERE e.thread_id=? AND e.id<>? AND d.status='done' "
                "ORDER BY b.date_jst DESC LIMIT ?", (thread_id, event_id, n))]


def build(db, brief_id, event=None, query_ja=None, query_en=None):
    """Assemble the full bundle. `event` is an events row when called from the pipeline."""
    qja = query_ja or (event and event["query_ja"]) or (event and event["title_ja"]) or ""
    qen = query_en or (event and event["query_en"]) or (event and event["title_en"]) or qja
    b = {
        "generated_at_jst": datetime.now(JST).isoformat(timespec="seconds"),
        "market_snapshot": market.load(db, brief_id) if brief_id else market.snapshot(),
        "prediction_markets": {"note": PM_NOTE, "polymarket": polymarket(),
                               "kalshi_structure_only": kalshi_structure()},
        "watchlist": watchlist(db),
        "articles_ja": news(qja, lang="ja"),
        "articles_en": news(qen, lang="en"),
    }
    if event is not None:
        thread = db.execute("SELECT slug,name FROM threads WHERE id=?",
                            (event["thread_id"],)).fetchone() if event["thread_id"] else None
        b["event"] = {
            "title_en": event["title_en"], "title_ja": event["title_ja"],
            "triage_risk_score": event["risk_score"],
            "triage_risk_direction": event["risk_direction"],
            "triage_rationale": event["why"],
            "thread": dict(thread) if thread else None,
        }
        b["source_headlines"] = event_items(db, event["id"])
        b["thread_prior_entries"] = thread_context(db, event["thread_id"], event["id"])
    else:
        b["event_query"] = qja
    return b


def arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: bundle.py "<ja query>" [--query-en "<en query>"] [--out FILE]')
    query = sys.argv[1]
    with dbm.connect() as db:
        row = db.execute("SELECT id FROM briefs ORDER BY date_jst DESC LIMIT 1").fetchone()
        b = build(db, row["id"] if row else None,
                  query_ja=query, query_en=arg("--query-en", query))
    txt = json.dumps(b, ensure_ascii=False, indent=2)
    if "--out" in sys.argv:
        open(arg("--out"), "w").write(txt)
        print(f"wrote {arg('--out')} ({len(txt)} bytes)")
    else:
        print(txt)


if __name__ == "__main__":
    main()
