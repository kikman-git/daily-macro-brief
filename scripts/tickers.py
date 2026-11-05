#!/usr/bin/env python3
"""The TSE ticker mirror behind the watchlist picker.

JPX publishes the whole listed universe as one spreadsheet (東証上場銘柄一覧, `data_j.xls`,
refreshed at each month end). Mirroring it locally turns "add a position" from four
hand-typed fields into one fuzzy search, and means the ticker/name/market/sector that reach
the dive prompt are JPX's strings rather than whatever got typed at 6am.

Two name columns, because they answer different queries:

- `name_ja` is JPX's own 銘柄名 — authoritative, complete, and the only name for 3,900 names.
- `name_en` is an *optional* Yahoo backfill (`--names`). It is what makes a latin query like
  "lasertec" resolve to 6920 at all: JPX ships no English column, and a kanji name cannot be
  romanised locally. Without it latin search still works for the ~40% of names written in
  kana (via `romaji`) plus anything already latin in the JPX string (ＫＤＤＩ → KDDI).

`romaji` holds two variants per name (sokuon doubled and dropped: "rezatekku rezateku"), so
both ways a person actually types レーザーテック hit the same row. Long-vowel marks are
dropped rather than doubled for the same reason.

Runs on the venv interpreter — `xlrd` is not installed in the system python:

    PYTHONPATH=scripts .venv/bin/python scripts/tickers.py --sync
    PYTHONPATH=scripts .venv/bin/python scripts/tickers.py --names      # slow, optional
    PYTHONPATH=scripts .venv/bin/python scripts/tickers.py --search レーザー
"""
import argparse
import json
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import db as dbm

JPX_URL = ("https://www.jpx.co.jp/markets/statistics-equities/misc/"
           "tvdivq0000001vg2-att/data_j.xls")
UA = "Mozilla/5.0 (daily-feeds ticker sync)"

# 市場・商品区分 → (display market, kind). The display strings match what the watchlist
# already holds ("TSE Growth"), so the picker doesn't fork the vocabulary the dives read.
MARKETS = {
    "プライム（内国株式）": ("TSE Prime", "equity"),
    "スタンダード（内国株式）": ("TSE Standard", "equity"),
    "グロース（内国株式）": ("TSE Growth", "equity"),
    "プライム（外国株式）": ("TSE Prime (foreign)", "equity"),
    "スタンダード（外国株式）": ("TSE Standard (foreign)", "equity"),
    "グロース（外国株式）": ("TSE Growth (foreign)", "equity"),
    "ETF・ETN": ("ETF/ETN", "etf"),
    "REIT・ベンチャーファンド・カントリーファンド・インフラファンド": ("REIT/Fund", "reit"),
    "PRO Market": ("TSE PRO", "equity"),
    "出資証券": ("出資証券", "other"),
}

# A truncated download must not be able to empty the table; a real JPX file is ~4,400 rows.
MIN_PLAUSIBLE_ROWS = 2000
# How long before a name lookup that produced nothing is worth asking again. Yahoo does gain
# coverage of new listings, so "never retry" is wrong; weekly is just wasteful.
RETRY_DAYS = 30

# --- kana → romaji ------------------------------------------------------------------------
# Digraphs first (longest match wins). Only kana is transliterated: kanji needs `name_en`.
ROMAJI = {
    "キャ": "kya", "キュ": "kyu", "キョ": "kyo", "キェ": "kye",
    "シャ": "sha", "シュ": "shu", "ショ": "sho", "シェ": "she",
    "チャ": "cha", "チュ": "chu", "チョ": "cho", "チェ": "che",
    "ニャ": "nya", "ニュ": "nyu", "ニョ": "nyo",
    "ヒャ": "hya", "ヒュ": "hyu", "ヒョ": "hyo",
    "ミャ": "mya", "ミュ": "myu", "ミョ": "myo",
    "リャ": "rya", "リュ": "ryu", "リョ": "ryo",
    "ギャ": "gya", "ギュ": "gyu", "ギョ": "gyo",
    "ジャ": "ja", "ジュ": "ju", "ジョ": "jo", "ジェ": "je", "ジィ": "ji",
    "ビャ": "bya", "ビュ": "byu", "ビョ": "byo",
    "ピャ": "pya", "ピュ": "pyu", "ピョ": "pyo",
    "ファ": "fa", "フィ": "fi", "フェ": "fe", "フォ": "fo", "フュ": "fyu",
    "ティ": "ti", "トゥ": "tu", "テュ": "tyu", "ディ": "di", "ドゥ": "du", "デュ": "dyu",
    "ツァ": "tsa", "ツィ": "tsi", "ツェ": "tse", "ツォ": "tso",
    "ウィ": "wi", "ウェ": "we", "ウォ": "wo",
    "ヴァ": "va", "ヴィ": "vi", "ヴェ": "ve", "ヴォ": "vo", "ヴュ": "vyu",
    "クァ": "kwa", "クィ": "kwi", "クェ": "kwe", "クォ": "kwo", "グァ": "gwa",
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo",
    "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヰ": "i", "ヱ": "e", "ヲ": "o", "ン": "n",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "ヴ": "vu", "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o",
    "ャ": "ya", "ュ": "yu", "ョ": "yo", "ヮ": "wa",
}


def to_katakana(s):
    """NFKC-fold, then hiragana → katakana so one table covers both scripts."""
    s = unicodedata.normalize("NFKC", s)
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


def _transliterate(kana, *, double_sokuon):
    out, i, pending = [], 0, False
    while i < len(kana):
        two = kana[i:i + 2]
        if two in ROMAJI:
            syl, step = ROMAJI[two], 2
        elif kana[i] in ROMAJI:
            syl, step = ROMAJI[kana[i]], 1
        elif kana[i] == "ッ":
            pending, i = double_sokuon, i + 1
            continue
        elif kana[i] == "ー":                     # long mark: dropped, never doubled
            i += 1
            continue
        else:
            # Latin/digits pass through (ＫＤＤＩ → kddi); kanji has no local reading.
            c = kana[i].lower()
            if c.isascii() and c.isalnum():
                out.append(c)
            i += 1
            continue
        if pending and syl:
            out.append(syl[0])                    # テック → tekku
            pending = False
        out.append(syl)
        i += step
    return "".join(out)


def romanise(name):
    """Space-separated romaji variants, or None when the name carries no kana at all."""
    kana = to_katakana(name)
    if not any(c in ROMAJI or c in "ッー" for c in kana):
        return None
    variants, seen = [], set()
    for double in (True, False):
        v = _transliterate(kana, double_sokuon=double)
        if v and v not in seen:
            seen.add(v)
            variants.append(v)
    return " ".join(variants) or None


# --- run bookkeeping ---------------------------------------------------------------------
# A run started while another is still going would race the same rows for no benefit; anything
# older than this is a crashed run, not a live one, and must not block the schedule forever.
STALE_RUN_MIN = 30


class Job:
    """One `ticker_syncs` row, opened on start and closed on the way out either way.

    The dashboard reads this table, so a crash has to leave `status='error'` with the message
    rather than a row stuck on 'running' — an invisible failed refresh is the one outcome that
    makes a scheduled sync worse than no sync.
    """

    def __init__(self, db, trigger, phase):
        self.db = db
        self.id = None
        self.outcome = None          # set by skip(); otherwise __exit__ decides from the exception
        self.trigger, self.phase = trigger, phase

    def __enter__(self):
        cur = self.db.execute(
            "INSERT INTO ticker_syncs(trigger,phase,status,started_at) VALUES(?,?,'running',?)",
            (self.trigger, self.phase, dbm.now_utc()))
        self.id = cur.lastrowid
        self.db.commit()
        return self

    def update(self, **fields):
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE ticker_syncs SET {sets} WHERE id=?",
                        (*fields.values(), self.id))
        self.db.commit()

    def skip(self, reason):
        self.outcome = "skipped"
        self.update(error=reason)

    def __exit__(self, exc_type, exc, tb):
        self.update(status=self.outcome or ("error" if exc else "ok"),
                    finished_at=dbm.now_utc(),
                    **({"error": f"{exc_type.__name__}: {exc}"} if exc else {}))
        return False


def reap_stale(db):
    """Mark abandoned 'running' rows as errors, and report whether one is genuinely live.

    The cutoff is computed in Python on purpose: this schema stores instants as
    `2026-08-05T14:00:00+00:00`, while SQLite's `datetime('now')` yields
    `2026-08-05 14:00:00` — and 'T' sorts above ' ', so a string comparison against it silently
    never matches a same-day row. Same-day is exactly the case that matters here.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STALE_RUN_MIN)) \
        .isoformat(timespec="seconds")
    db.execute(
        "UPDATE ticker_syncs SET status='error', finished_at=?, "
        "error='abandoned — process died without finishing' "
        "WHERE status='running' AND started_at < ?", (dbm.now_utc(), cutoff))
    db.commit()
    return db.execute("SELECT COUNT(*) c FROM ticker_syncs WHERE status='running'").fetchone()["c"]


# --- JPX spreadsheet ---------------------------------------------------------------------
def fetch_xls(path=None):
    if path:
        return open(path, "rb").read()
    req = urllib.request.Request(JPX_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def cell(v):
    """xlrd hands back floats for numeric cells; codes and sector codes must not gain '.0'."""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def dash(v):
    """JPX writes '-' where a column doesn't apply (an ETF has no 33業種)."""
    return v if v and v != "-" else None


def parse(blob):
    import xlrd

    sh = xlrd.open_workbook(file_contents=blob).sheet_by_index(0)
    header = [cell(sh.cell_value(0, c)) for c in range(sh.ncols)]
    want = ["日付", "コード", "銘柄名", "市場・商品区分", "33業種区分", "17業種区分", "規模区分"]
    missing = [w for w in want if w not in header]
    if missing:
        raise RuntimeError(f"JPX layout changed — columns missing: {missing} (got {header})")
    at = {w: header.index(w) for w in want}

    rows = []
    for r in range(1, sh.nrows):
        code = cell(sh.cell_value(r, at["コード"]))
        name = cell(sh.cell_value(r, at["銘柄名"]))
        if not code or not name:
            continue
        seg = cell(sh.cell_value(r, at["市場・商品区分"]))
        market, kind = MARKETS.get(seg, (seg, "other"))
        # Common stock is 4 characters ('7203', '130A'); the 5-character issues are
        # 優先株式/社債型種類株式 (94345 = ソフトバンク第１回社債型種類株式). They are listed, so they stay
        # searchable, but they are never what "my position in SoftBank" means — demoting them
        # out of `equity` keeps them below the common line in the picker.
        if len(code) != 4:
            kind = "other"
        rows.append({
            "code": code,
            "name_ja": name,
            "romaji": romanise(name),
            "market": market,
            "kind": kind,
            "sector33": dash(cell(sh.cell_value(r, at["33業種区分"]))),
            "sector17": dash(cell(sh.cell_value(r, at["17業種区分"]))),
            "scale": dash(cell(sh.cell_value(r, at["規模区分"]))),
            "asof": cell(sh.cell_value(r, at["日付"])),
        })
    return rows


def sync(path=None, prune=True, db=None, job=None):
    rows = parse(fetch_xls(path))
    if len(rows) < MIN_PLAUSIBLE_ROWS:
        raise RuntimeError(f"only {len(rows)} rows parsed (<{MIN_PLAUSIBLE_ROWS}) — refusing to "
                           f"overwrite the table from what looks like a truncated download")
    now = dbm.now_utc()
    db = db or dbm.connect()
    # Snapshot the columns JPX owns, so the run can report what actually moved rather than just
    # "4,444 rows written" — three weeks in four the file is unchanged and that should be visible.
    prior = {r["code"]: (r["name_ja"], r["market"], r["sector33"], r["scale"])
             for r in db.execute("SELECT code, name_ja, market, sector33, scale FROM tickers")}
    added = sum(1 for r in rows if r["code"] not in prior)
    changed = sum(1 for r in rows if r["code"] in prior
                  and prior[r["code"]] != (r["name_ja"], r["market"], r["sector33"], r["scale"]))
    before = len(prior)
    # name_en is ours, not JPX's: a re-sync must never wipe the backfill.
    db.executemany(
        "INSERT INTO tickers(code,name_ja,romaji,market,kind,sector33,sector17,scale,asof,"
        "updated_at) VALUES(:code,:name_ja,:romaji,:market,:kind,:sector33,:sector17,:scale,"
        ":asof,:updated_at) "
        "ON CONFLICT(code) DO UPDATE SET name_ja=excluded.name_ja, romaji=excluded.romaji, "
        "market=excluded.market, kind=excluded.kind, sector33=excluded.sector33, "
        "sector17=excluded.sector17, scale=excluded.scale, asof=excluded.asof, "
        "updated_at=excluded.updated_at",
        [dict(r, updated_at=now) for r in rows])
    dropped = 0
    if prune:
        live = {r["code"] for r in rows}
        gone = [r["code"] for r in db.execute("SELECT code FROM tickers").fetchall()
                if r["code"] not in live]
        db.executemany("DELETE FROM tickers WHERE code=?", [(c,) for c in gone])
        dropped = len(gone)
    asof = rows[0]["asof"]
    if job:
        job.update(asof=asof, rows_seen=len(rows), added=added, changed=changed, delisted=dropped)
    db.commit()
    total = db.execute("SELECT COUNT(*) c FROM tickers").fetchone()["c"]
    print(f"synced {len(rows)} JPX listings (as of {asof}); table {before} → {total}"
          f" (+{added} new, {changed} changed"
          + (f", −{dropped} delisted" if dropped else "") + ")")
    return {"asof": asof, "rows_seen": len(rows), "added": added, "changed": changed,
            "delisted": dropped}


# --- optional English-name backfill ------------------------------------------------------
def yahoo_name(code, timeout=15):
    """(longName, shortName) from the same free chart endpoint market.py already uses."""
    u = ("https://query1.finance.yahoo.com/v8/finance/chart/"
         f"{urllib.parse.quote(code)}.T?range=1d&interval=1d")
    req = urllib.request.Request(u, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        meta = json.load(r)["chart"]["result"][0]["meta"]
    return meta.get("longName"), meta.get("shortName")


def backfill_names(limit=None, sleep=0.5, kinds=("equity",), db=None, job=None):
    """Fill missing name_en, slowly and resumably.

    Deliberately not part of --sync: it is ~3,900 requests to a free endpoint that the daily
    market snapshot also depends on, so it is throttled, restartable (it only ever looks at
    rows still missing a name), and gives up after a run of failures rather than hammering on.
    """
    db = db or dbm.connect()
    # Never-tried codes first, then anything last tried longer ago than RETRY_DAYS. Without this
    # the weekly run spends its whole cap re-asking Yahoo about the same few hundred names it has
    # never had (PRO Market shells, some new listings) and never reaches this week's IPOs —
    # ordering by code alone put the hopeless ones first, permanently.
    stale = (datetime.now(timezone.utc) - timedelta(days=RETRY_DAYS)).isoformat(timespec="seconds")
    q = (f"SELECT code FROM tickers WHERE name_en IS NULL AND kind IN "
         f"({','.join('?' * len(kinds))}) AND (name_tried_at IS NULL OR name_tried_at < ?) "
         f"ORDER BY name_tried_at IS NOT NULL, code")
    todo = [r["code"] for r in db.execute(q, (*kinds, stale)).fetchall()]
    if limit:
        todo = todo[:limit]
    print(f"{len(todo)} row(s) missing name_en; ~{len(todo) * sleep / 60:.0f} min at {sleep}s apart",
          flush=True)
    ok, fail, streak = 0, 0, 0
    for i, code in enumerate(todo, 1):
        try:
            long_name, short_name = yahoo_name(code)
            name = long_name or short_name
            now = dbm.now_utc()
            # Stamp the attempt whether or not it produced a name — that stamp is what stops a
            # name Yahoo does not carry from being asked for again next week.
            if name:
                db.execute(
                    "UPDATE tickers SET name_en=?, name_tried_at=?, updated_at=? WHERE code=?",
                    (name.strip(), now, now, code))
                ok += 1
            else:
                db.execute("UPDATE tickers SET name_tried_at=? WHERE code=?", (now, code))
            # Commit per row, not per batch. Batching held a write transaction open across
            # ~22s of HTTP waits, and the dashboard's own writes (saving a position) got
            # SQLITE_BUSY the whole time — a half-hour backfill must not lock the UI out.
            db.commit()
            streak = 0
        except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError) as e:
            fail, streak = fail + 1, streak + 1
            # A 404 for a code Yahoo does not cover is a fact about that code, so it is stamped
            # like any other miss. A 429 or a dead network is not, but the streak guard below
            # stops the run before those can stamp much.
            db.execute("UPDATE tickers SET name_tried_at=? WHERE code=?", (dbm.now_utc(), code))
            db.commit()
            if streak >= 20:
                print(f"  stopping: 20 consecutive failures (last: {type(e).__name__} {e})")
                break
        if i % 50 == 0:
            print(f"  {i}/{len(todo)} — {ok} named, {fail} failed", flush=True)
        time.sleep(sleep)
    db.commit()
    total = db.execute("SELECT COUNT(*) c FROM tickers WHERE name_en IS NOT NULL").fetchone()["c"]
    if job:
        job.update(names_added=ok)
    print(f"backfilled {ok} name(s), {fail} failed; {total} rows now carry an English name")
    return {"names_added": ok, "failed": fail}


# --- read-side helpers (sanity checks; the picker scores in web/lib/tickers.ts) -----------
def stats():
    db = dbm.connect()   # not read_only: creates the table if this box has never synced
    rows = db.execute("SELECT market, kind, COUNT(*) c, "
                      "SUM(name_en IS NOT NULL) en, SUM(romaji IS NOT NULL) ro "
                      "FROM tickers GROUP BY market, kind ORDER BY c DESC").fetchall()
    if not rows:
        db.close()
        sys.exit("tickers table is empty — run --sync first")
    asof = db.execute("SELECT MAX(asof) a FROM tickers").fetchone()["a"]
    print(f"JPX snapshot {asof}")
    print(f"{'market':24} {'kind':7} {'rows':>6} {'name_en':>8} {'romaji':>7}")
    for r in rows:
        print(f"{r['market']:24} {r['kind']:7} {r['c']:6d} {r['en']:8d} {r['ro']:7d}")
    t = db.execute("SELECT COUNT(*) c, SUM(name_en IS NOT NULL) en FROM tickers").fetchone()
    print(f"{'total':24} {'':7} {t['c']:6d} {t['en']:8d}")
    # The interesting number is not "how many names are missing" but "how many are missing that
    # we have not already asked about" — the rest are names Yahoo does not carry.
    m = db.execute("SELECT SUM(name_en IS NULL) miss, "
                   "SUM(name_en IS NULL AND name_tried_at IS NOT NULL) asked "
                   "FROM tickers WHERE kind='equity'").fetchone()
    print(f"equities without an English name: {m['miss']} "
          f"({m['asked']} already looked up and not carried by Yahoo)")
    db.close()


def search(q, limit=10):
    """Substring probe — a check that the table holds what you think, not the picker's ranking."""
    needle = f"%{to_katakana(q).lower()}%"
    db = dbm.connect()
    rows = db.execute(
        "SELECT code, name_ja, name_en, market, sector33 FROM tickers "
        "WHERE code LIKE ? OR name_ja LIKE ? OR LOWER(name_en) LIKE ? OR romaji LIKE ? "
        "ORDER BY kind='equity' DESC, code LIMIT ?",
        (needle, needle, needle, needle, limit)).fetchall()
    for r in rows:
        print(f"{r['code']:6} {r['name_ja']:<24} {r['name_en'] or '—':<34} "
              f"{r['market']:<14} {r['sector33'] or ''}")
    print(f"— {len(rows)} hit(s)")
    db.close()


def runs(limit=10):
    """Recent sync history — the same rows the dashboard's mirror panel lists."""
    db = dbm.connect()
    reap_stale(db)
    rows = db.execute("SELECT * FROM ticker_syncs ORDER BY started_at DESC LIMIT ?",
                      (limit,)).fetchall()
    if not rows:
        print("no runs recorded yet")
    for r in rows:
        delta = " ".join(f"{k}={r[k]}" for k in
                         ("added", "changed", "delisted", "names_added") if r[k])
        print(f"{r['started_at']}  {r['trigger']:6} {r['phase']:11} {r['status']:8} "
              f"{r['asof'] or '—':9} {delta or '(no change)'}"
              + (f"  {r['error']}" if r["error"] else ""))
    db.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sync", action="store_true", help="refresh from JPX (the default)")
    ap.add_argument("--weekly", action="store_true",
                    help="what the timer and the dashboard button run: sync + fill new listings")
    ap.add_argument("--file", help="parse a local data_j.xls instead of downloading")
    ap.add_argument("--no-prune", action="store_true", help="keep codes JPX no longer lists")
    ap.add_argument("--names", action="store_true", help="backfill English names from Yahoo")
    ap.add_argument("--limit", type=int, help="cap rows for --names")
    ap.add_argument("--sleep", type=float, default=0.5, help="seconds between --names requests")
    ap.add_argument("--trigger", default="cli", choices=("timer", "manual", "cli"),
                    help="who started this run; recorded on the job row")
    ap.add_argument("--stats", action="store_true", help="coverage by market")
    ap.add_argument("--runs", action="store_true", help="recent sync history")
    ap.add_argument("--search", metavar="Q", help="substring probe against the mirror")
    a = ap.parse_args()

    if a.search:
        return search(a.search)
    if a.stats:
        return stats()
    if a.runs:
        return runs()

    phase = "sync+names" if a.weekly else ("names" if a.names else "sync")
    db = dbm.connect()
    if reap_stale(db):
        # Exit 0, not an error: the schedule firing while a manual run is mid-flight is normal,
        # and a red unit for it would train the eye to ignore red units.
        with Job(db, a.trigger, phase) as job:
            job.skip("another run was still in progress")
        print("another run is already in progress — skipping")
        db.close()
        return
    try:
        with Job(db, a.trigger, phase) as job:
            if a.weekly or not a.names:
                sync(path=a.file, prune=not a.no_prune, db=db, job=job)
            if a.weekly or a.names:
                # Weekly, this only has this week's IPOs to look up (plus any name Yahoo has
                # never had), so the cap is a guard against a first run, not the normal case.
                backfill_names(limit=a.limit or (250 if a.weekly else None),
                               sleep=a.sleep, db=db, job=job)
    finally:
        db.close()


if __name__ == "__main__":
    main()
