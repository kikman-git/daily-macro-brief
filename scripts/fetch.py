#!/usr/bin/env python3
"""Stage 1 — ingest. Pulls the registry in SOURCES.md into SQLite.

Dedupes by URL and gates on a 48h publication window. Feed failures are recorded per-feed
(`feeds.last_status`) and never abort the run: one dead feed must not cost the morning brief.

Usage: fetch.py [--hours 48] [--date YYYY-MM-DD]
"""
import concurrent.futures as cf
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import db as dbm
import feeds as registry

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"}


def tag(el):
    """Local tag name, namespace stripped — Atom/RDF feeds are namespaced, RSS 2.0 is not."""
    return el.tag.rsplit("}", 1)[-1] if "}" in el.tag else el.tag


def text(el, *names):
    """First non-empty value among `names`, in *argument* order — not document order.

    The distinction matters: MarketWatch emits <guid>WP-MKTW-0005160879</guid> before <link>,
    so scanning children in document order returned an opaque internal id as the article URL
    for every one of its items. Argument order makes the preference explicit.
    """
    by_tag = {}
    for child in el:
        t = tag(child)
        if t in names and t not in by_tag:
            val = (child.text or "").strip()
            if not val and "href" in child.attrib:   # Atom <link href="..."/> carries no text
                val = child.attrib["href"].strip()
            if val:
                by_tag[t] = val
    for n in names:
        if n in by_tag:
            return by_tag[n]
    return None


def parse_date(raw):
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def parse_feed(blob):
    """Yield dicts from RSS 2.0 <item>, Atom <entry>, or RDF <item>."""
    root = ET.fromstring(blob)
    out = []
    for el in root.iter():
        if tag(el) not in ("item", "entry"):
            continue
        url = text(el, "link", "id", "guid")
        title = text(el, "title")
        if not url or not title:
            continue
        out.append({
            "url": url,
            "title": title,
            "source": text(el, "source"),
            "published": parse_date(text(el, "pubDate", "published", "updated", "date")),
            "summary": (text(el, "description", "summary", "content") or "")[:1200] or None,
        })
    return out


def fetch_one(feed, cutoff):
    try:
        req = urllib.request.Request(feed["url"], headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            blob = r.read()
        items = parse_feed(blob)
    except Exception as e:
        return feed, [], f"{type(e).__name__}: {e}"
    # No date is treated as new: several official feeds omit pubDate, and URL dedupe
    # already prevents us from re-ingesting the same article.
    kept = [i for i in items if i["published"] is None or i["published"] >= cutoff]
    return feed, kept, f"ok {len(kept)}/{len(items)}"


def main():
    hours = int(sys.argv[sys.argv.index("--hours") + 1]) if "--hours" in sys.argv else 48
    date_jst = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    now = dbm.now_utc()

    db = dbm.connect()
    dbm.get_or_create_brief(db, date_jst)
    rows = registry.sync(db, now)
    feed_list = [dict(r) for r in rows]

    new = dupe = 0
    failures = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda f: fetch_one(f, cutoff), feed_list))

    for feed, items, status in results:
        db.execute("UPDATE feeds SET last_fetch_at=?, last_status=? WHERE id=?",
                   (now, status, feed["id"]))
        if not status.startswith("ok"):
            failures.append(f"{feed['name']}: {status}")
        for it in items:
            cur = db.execute(
                "INSERT INTO items(feed_id,url,title,source,published_at,fetched_at,summary,lang) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(url) DO NOTHING",
                (feed["id"], it["url"], it["title"], it["source"],
                 it["published"].isoformat(timespec="seconds") if it["published"] else None,
                 now, it["summary"], feed["lang"]))
            if cur.rowcount:
                new += 1
            else:
                dupe += 1
    db.commit()

    fresh = db.execute(
        "SELECT COUNT(*) c FROM items WHERE COALESCE(published_at, fetched_at) >= ?",
        (cutoff.isoformat(timespec="seconds"),)).fetchone()["c"]
    print(f"feeds={len(feed_list)} new={new} dupe={dupe} in-window={fresh}")
    for f in failures:
        print(f"  FAIL {f}", file=sys.stderr)
    db.close()


if __name__ == "__main__":
    main()
