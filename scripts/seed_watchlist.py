#!/usr/bin/env python3
"""One-shot import of config/watchlist.json into the SQLite watchlist.

The dashboard is the normal way to edit the watchlist (SPEC decision 6). This exists for the
file-first path: fill in a copy of config/watchlist.example.json, run this once, then edit in
the UI from then on.

Idempotent — re-running updates existing tickers rather than duplicating them.

Usage: seed_watchlist.py [path]   (default: config/watchlist.json)
"""
import json
import sys
from pathlib import Path

import db as dbm

DEFAULT = Path(__file__).resolve().parent.parent / "config/watchlist.json"


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not path.exists():
        sys.exit(f"no such file: {path}\n"
                 f"copy config/watchlist.example.json to config/watchlist.json first, "
                 f"or just use the dashboard at :8446/watchlist")
    data = json.loads(path.read_text())
    now = dbm.now_utc()

    db = dbm.connect()
    n = 0
    for p in data.get("positions", []):
        ticker = (p.get("ticker") or "").strip()
        name = (p.get("name") or "").strip()
        if not ticker or not name or "PLACEHOLDER" in name.upper():
            continue
        db.execute(
            "INSERT INTO watchlist(ticker,name,market,sector,status,beta_tag,drivers_json,"
            "thesis,updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, market=excluded.market, "
            "sector=excluded.sector, status=excluded.status, beta_tag=excluded.beta_tag, "
            "drivers_json=excluded.drivers_json, thesis=excluded.thesis, "
            "updated_at=excluded.updated_at",
            (ticker, name, p.get("market"), p.get("sector"),
             p.get("status") if p.get("status") in ("hold", "watch") else "watch",
             p.get("beta_tag") if p.get("beta_tag") in ("high", "mid", "low") else "mid",
             json.dumps(p.get("drivers") or [], ensure_ascii=False), p.get("thesis"), now))
        n += 1
    if data.get("book_style"):
        dbm.set_setting(db, "book_style", data["book_style"])
    if data.get("sectors_of_interest"):
        dbm.set_setting(db, "sectors_of_interest", data["sectors_of_interest"])
    db.commit()
    total = db.execute("SELECT COUNT(*) c FROM watchlist").fetchone()["c"]
    print(f"imported {n} position(s) from {path.name}; watchlist now holds {total}")
    db.close()


if __name__ == "__main__":
    main()
