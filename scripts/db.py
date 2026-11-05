#!/usr/bin/env python3
"""SQLite layer for daily-feeds. Every other script imports connect() from here.

Timestamp convention: instants are stored as UTC ISO-8601 ("...+00:00"); only
`briefs.date_jst` is a Japan-local calendar date, because the brief is named after the
trading morning it serves.

WAL is required, not cosmetic: the Next.js reader holds a read-only handle open while
the Python stages write.
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

DB_PATH = os.environ.get("DAILY_FEEDS_DB") or os.path.expanduser(
    "~/.openclaw/data/daily-feeds.sqlite")

# Audio sits beside the DB rather than inside it, following the myself-media convention.
AUDIO_DIR = os.environ.get("DAILY_FEEDS_AUDIO") or os.path.expanduser(
    "~/.openclaw/data/daily-feeds-audio")

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- One row per trading morning.
CREATE TABLE IF NOT EXISTS briefs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  date_jst     TEXT NOT NULL UNIQUE,
  status       TEXT NOT NULL DEFAULT 'pending',  -- pending|triaged|published|error
  started_at   TEXT NOT NULL,
  published_at TEXT,
  regime_note  TEXT,
  error        TEXT                              -- surfaced on the dashboard, never swallowed
);

CREATE TABLE IF NOT EXISTS feeds (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  url           TEXT NOT NULL UNIQUE,
  kind          TEXT NOT NULL,                   -- jp-official|jp-news|jp-analysis|jp-adapter|us-official|us-news
  lang          TEXT NOT NULL,
  enabled       INTEGER NOT NULL DEFAULT 1,
  last_fetch_at TEXT,
  last_status   TEXT                             -- 'ok N' or the exception, for the health page
);

CREATE TABLE IF NOT EXISTS items (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  feed_id      INTEGER NOT NULL REFERENCES feeds(id),
  url          TEXT NOT NULL UNIQUE,             -- dedupe key
  title        TEXT NOT NULL,
  title_en     TEXT,
  source       TEXT,                             -- publisher name (Google News supplies this)
  published_at TEXT,
  fetched_at   TEXT NOT NULL,
  summary      TEXT,
  lang         TEXT
);
CREATE INDEX IF NOT EXISTS items_published ON items(published_at DESC);

-- Long-lived themes. Dives receive the prior entries on their thread; that continuity is
-- the whole point of decision 14.
CREATE TABLE IF NOT EXISTS threads (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  slug         TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  last_seen_at TEXT,
  summary      TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  brief_id       INTEGER NOT NULL REFERENCES briefs(id) ON DELETE CASCADE,
  title_en       TEXT NOT NULL,
  title_ja       TEXT,
  risk_score     INTEGER NOT NULL,               -- 0-100, risk-on/off POTENTIAL not newsworthiness
  risk_direction TEXT,                           -- risk-on|risk-off|ambiguous
  tier           TEXT NOT NULL,                  -- deep|thin
  rank           INTEGER NOT NULL DEFAULT 0,
  why            TEXT,                           -- one-line transmission channel
  thread_id      INTEGER REFERENCES threads(id),
  query_ja       TEXT,                           -- triage-authored search queries for the dive bundle
  query_en       TEXT
);
CREATE INDEX IF NOT EXISTS events_brief ON events(brief_id, rank);

CREATE TABLE IF NOT EXISTS event_items (
  event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  item_id  INTEGER NOT NULL REFERENCES items(id),
  PRIMARY KEY (event_id, item_id)
);

CREATE TABLE IF NOT EXISTS dives (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id            INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  status              TEXT NOT NULL,             -- researching|done|error
  model               TEXT,
  started_at          TEXT,
  finished_at         TEXT,
  verdict             TEXT,                      -- risk-on|risk-off|ambiguous
  confidence          TEXT,
  horizon             TEXT,
  jp_equity_direction TEXT,
  high_beta_note      TEXT,
  falsifier           TEXT,
  body_md             TEXT,
  sources_json        TEXT,
  error               TEXT
);
CREATE INDEX IF NOT EXISTS dives_event ON dives(event_id);

CREATE TABLE IF NOT EXISTS market_snapshots (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  brief_id    INTEGER NOT NULL REFERENCES briefs(id) ON DELETE CASCADE,
  symbol      TEXT NOT NULL,
  label       TEXT,
  last        REAL,
  chg_pct     REAL,
  extras_json TEXT,                              -- MA distance, drawdown, realized vol
  asof        TEXT,
  UNIQUE (brief_id, symbol)
);

-- Source of truth for the watchlist (edited in the UI; see SPEC decision 6).
CREATE TABLE IF NOT EXISTS watchlist (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker       TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  market       TEXT,
  sector       TEXT,
  status       TEXT NOT NULL DEFAULT 'watch',    -- hold|watch
  beta_tag     TEXT NOT NULL DEFAULT 'mid',      -- high|mid|low
  drivers_json TEXT,
  thesis       TEXT,
  updated_at   TEXT NOT NULL
);

-- The TSE listed universe, mirrored from JPX's 東証上場銘柄一覧 (data_j.xls) by
-- scripts/tickers.py. Read-only reference data: it exists so adding a position is one
-- fuzzy search instead of four hand-typed fields, and so the ticker/name/market/sector
-- the dive prompt sees come from JPX rather than from typing.
CREATE TABLE IF NOT EXISTS tickers (
  code       TEXT PRIMARY KEY,               -- 4-char TSE code; alphanumeric ('130A') included
  name_ja    TEXT NOT NULL,                  -- as JPX prints it (full-width, mixed scripts)
  name_en    TEXT,                           -- optional Yahoo backfill: what makes "lasertec" hit
  name_tried_at TEXT,                        -- last name lookup attempt, hit or miss
  romaji     TEXT,                            -- kana → romaji variants, derived locally
  market     TEXT NOT NULL,                  -- TSE Prime|TSE Standard|TSE Growth|ETF/ETN|…
  kind       TEXT NOT NULL,                  -- equity|etf|reit|other
  sector33   TEXT,
  sector17   TEXT,
  scale      TEXT,                           -- TOPIX Core30 … Small 2; drives the beta suggestion
  asof       TEXT,                           -- the JPX file's own 日付, so staleness is visible
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tickers_name ON tickers(name_ja);

-- One row per run of scripts/tickers.py, whichever way it was started. The mirror is the only
-- table fed from outside on a schedule, so "did the weekly refresh actually happen, and what
-- changed" has to be answerable from the dashboard rather than from journalctl over SSH.
CREATE TABLE IF NOT EXISTS ticker_syncs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger      TEXT NOT NULL,                   -- timer|manual|cli (systemd instance name)
  phase        TEXT NOT NULL,                   -- sync|names|sync+names
  status       TEXT NOT NULL,                   -- running|ok|error|skipped
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  asof         TEXT,                            -- the JPX 日付 this run saw
  rows_seen    INTEGER,
  added        INTEGER,                         -- codes JPX lists that we didn't have
  changed      INTEGER,                         -- name/market/sector/scale edits on existing codes
  delisted     INTEGER,
  names_added  INTEGER,
  error        TEXT
);
CREATE INDEX IF NOT EXISTS ticker_syncs_started ON ticker_syncs(started_at DESC);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Spoken versions of the morning. A row is either one dive's track (event_id set) or the
-- roll-up covering the whole brief (event_id NULL). Its own table rather than columns on
-- dives: the roll-up belongs to no single event, and re-synthesising audio must never be
-- able to touch dive text.
-- The audio itself lives on disk, not in the DB -- a 6-minute AAC track is ~2MB and the
-- Next.js reader holds this file open read-only.
CREATE TABLE IF NOT EXISTS audio (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  brief_id   INTEGER NOT NULL REFERENCES briefs(id) ON DELETE CASCADE,
  event_id   INTEGER REFERENCES events(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL,                     -- dive|rollup
  status     TEXT NOT NULL DEFAULT 'pending',   -- pending|done|error
  path       TEXT,
  bytes      INTEGER,
  duration_s REAL,
  chars      INTEGER,
  chunks     INTEGER,
  model      TEXT,
  voice      TEXT,
  script_txt TEXT,                              -- exactly what was spoken, for auditing
  created_at TEXT NOT NULL,
  error      TEXT
);
-- COALESCE, not a plain UNIQUE: SQLite treats NULLs as distinct, so a bare
-- UNIQUE(brief_id, kind, event_id) would happily insert a second roll-up every run.
CREATE UNIQUE INDEX IF NOT EXISTS audio_slot
  ON audio(brief_id, kind, COALESCE(event_id, -1));
"""


def _add_missing_columns(db):
    """Columns added to a table that already exists on this box.

    SCHEMA is all CREATE TABLE IF NOT EXISTS, which silently does nothing once a table is there —
    so a column added to it later never appears on an existing database. SQLite has no
    ADD COLUMN IF NOT EXISTS, hence the table_info check. Keep entries here forever: they are
    what makes a box that predates the column converge on the current schema.
    """
    want = {"tickers": {"name_tried_at": "TEXT"}}
    for table, cols in want.items():
        have = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        for col, decl in cols.items():
            if have and col not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def connect(path=None, read_only=False):
    p = path or DB_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if read_only:
        db = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=15)
    else:
        db = sqlite3.connect(p, timeout=30)
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        _add_missing_columns(db)
        db.commit()
    db.row_factory = sqlite3.Row
    return db


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_jst():
    return datetime.now(JST).date().isoformat()


def setting(db, key, default=None):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return row["value"]


def set_setting(db, key, value):
    db.execute("INSERT INTO settings(key,value) VALUES(?,?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value, ensure_ascii=False)))


def get_or_create_brief(db, date_jst=None):
    d = date_jst or today_jst()
    row = db.execute("SELECT * FROM briefs WHERE date_jst=?", (d,)).fetchone()
    if row:
        return row["id"]
    cur = db.execute("INSERT INTO briefs(date_jst, status, started_at) VALUES(?,'pending',?)",
                     (d, now_utc()))
    db.commit()
    return cur.lastrowid


def fail_brief(db, brief_id, message):
    """Record a visible broken state. A silent no-brief morning is the worst outcome."""
    db.execute("UPDATE briefs SET status='error', error=? WHERE id=?", (message, brief_id))
    db.commit()


def watchlist_dict(db):
    """Shape the watchlist the way the dive prompt expects, or a safe absent-marker."""
    rows = db.execute("SELECT * FROM watchlist ORDER BY status, ticker").fetchall()
    if not rows:
        return {"_absent": "No watchlist configured. Speak in sectors and Growth250 beta; "
                           "do not invent ticker names."}
    out = {
        "book_style": setting(db, "book_style", {
            "long": "small-cap / high-beta Japanese equities",
            "hedge": "short Nikkei 225 micro futures",
        }),
        "sectors_of_interest": setting(db, "sectors_of_interest", []),
        "positions": [],
    }
    for r in rows:
        try:
            drivers = json.loads(r["drivers_json"] or "[]")
        except Exception:
            drivers = []
        out["positions"].append({
            "ticker": r["ticker"], "name": r["name"], "market": r["market"],
            "sector": r["sector"], "status": r["status"], "beta_tag": r["beta_tag"],
            "drivers": drivers, "thesis": r["thesis"],
        })
    return out


if __name__ == "__main__":
    with connect() as db:
        n = len(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
        print(f"{DB_PATH}: schema ok, {n} tables")
