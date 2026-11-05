import { DatabaseSync } from "node:sqlite";
import os from "node:os";
import path from "node:path";
import type {
  AudioTrack,
  Brief,
  BriefEvent,
  Dive,
  MarketRow,
  WatchFields,
  WatchRow,
} from "./types";

const DB_PATH =
  process.env.DAILY_FEEDS_DB ?? path.join(os.homedir(), ".openclaw/data/daily-feeds.sqlite");
const AUDIO_DIR =
  process.env.DAILY_FEEDS_AUDIO ?? path.join(os.homedir(), ".openclaw/data/daily-feeds-audio");
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Absolute path for a finished track, or null. Server-only — the browser sees row ids.
 *
 *  The stored path is written by our own pipeline, but it is resolved and contained anyway:
 *  the value reaches a filesystem read from an HTTP route, and "it came from our own table" is
 *  exactly the assumption that turns one bad write into an arbitrary-file-read. */
export function audioFile(id: number): string | null {
  if (!Number.isInteger(id) || id <= 0) return null;
  return withDb(true, (db) => {
    const r = db.prepare("SELECT path, status FROM audio WHERE id = ?").all(id)[0] as
      | Row
      | undefined;
    if (!r || r.status !== "done" || !r.path) return null;
    const p = path.resolve(String(r.path));
    return p.startsWith(path.resolve(AUDIO_DIR) + path.sep) ? p : null;
  });
}

// The pipeline is the only writer of brief data; the UI writes nothing but the watchlist.
function withDb<T>(readOnly: boolean, fn: (db: DatabaseSync) => T): T {
  const db = new DatabaseSync(DB_PATH, { readOnly });
  // Wait for a writer instead of failing the request. Two processes write this file: the Python
  // stages during a run, and this app when a position is saved. Without a timeout the second one
  // gets SQLITE_BUSY the instant they overlap and the user sees "database is locked" for what is
  // really a few hundred milliseconds of contention.
  db.exec("PRAGMA busy_timeout = 5000");
  try {
    return fn(db);
  } finally {
    db.close();
  }
}

type Row = Record<string, string | number | null | Uint8Array>;
const str = (v: Row[string]): string | null => (v == null ? null : String(v));
const num = (v: Row[string]): number | null => (v == null ? null : Number(v));

function parseJson<T>(raw: Row[string], fallback: T): T {
  if (raw == null) return fallback;
  try {
    return JSON.parse(String(raw)) as T;
  } catch {
    return fallback;
  }
}

function marketRow(r: Row): MarketRow {
  const x = parseJson<Record<string, number | string | null>>(r.extras_json, {});
  return {
    symbol: String(r.symbol),
    label: str(r.label),
    last: num(r.last),
    chgPct: num(r.chg_pct),
    vsMa20Pct: (x.vs_ma20_pct as number) ?? null,
    vsMa50Pct: (x.vs_ma50_pct as number) ?? null,
    drawdownPct: (x.drawdown_from_60d_high_pct as number) ?? null,
    realizedVolPct: (x.realized_vol_20d_annualized_pct as number) ?? null,
    error: (x.error as string) ?? null,
  };
}

/** `path` is deliberately not exposed: the browser addresses tracks by row id only. */
function audioRow(r: Row | undefined): AudioTrack | null {
  if (!r) return null;
  return {
    id: Number(r.id),
    kind: String(r.kind) as AudioTrack["kind"],
    status: String(r.status) as AudioTrack["status"],
    durationS: num(r.duration_s),
    bytes: num(r.bytes),
    error: str(r.error),
  };
}

function diveRow(r: Row | undefined): Dive | null {
  if (!r) return null;
  return {
    status: String(r.status) as Dive["status"],
    model: str(r.model),
    startedAt: str(r.started_at),
    finishedAt: str(r.finished_at),
    verdict: str(r.verdict) as Dive["verdict"],
    confidence: str(r.confidence),
    horizon: str(r.horizon),
    jpEquityDirection: str(r.jp_equity_direction),
    highBetaNote: str(r.high_beta_note),
    falsifier: str(r.falsifier),
    bodyMd: str(r.body_md),
    sources: parseJson<string[]>(r.sources_json, []),
    error: str(r.error),
  };
}

/** One brief, fully hydrated. `date` omitted = the most recent brief on file. */
export function getBrief(date?: string | null): Brief | null {
  if (date && !DATE_RE.test(date)) return null;
  return withDb(true, (db) => {
    // Defaulting to the newest row by date is not enough: a brief with no market snapshot has
    // never had a real run behind it, and rendering one reads as "nothing cleared the relevance
    // floor today" — a false quiet day rather than an honest empty. Prefer the newest brief that
    // actually has computed market data, and only fall back to the raw newest if none does.
    const brief = (
      date
        ? db.prepare("SELECT * FROM briefs WHERE date_jst = ?").all(date)
        : db
            .prepare(
              `SELECT b.* FROM briefs b
               WHERE EXISTS (SELECT 1 FROM market_snapshots m WHERE m.brief_id = b.id)
               ORDER BY b.date_jst DESC LIMIT 1`
            )
            .all()
    )[0] as Row | undefined ??
    (date ? undefined : (db.prepare("SELECT * FROM briefs ORDER BY date_jst DESC LIMIT 1").all()[0] as Row | undefined));
    if (!brief) return null;
    const briefId = Number(brief.id);

    const events = (
      db
        .prepare(
          `SELECT e.*, t.slug thread_slug, t.name thread_name
           FROM events e LEFT JOIN threads t ON t.id = e.thread_id
           WHERE e.brief_id = ? ORDER BY e.rank`
        )
        .all(briefId) as Row[]
    ).map((e): BriefEvent => {
      const id = Number(e.id);
      const items = (
        db
          .prepare(
            `SELECT i.title, i.url, i.source, i.lang, i.published_at, f.name feed
             FROM event_items ei JOIN items i ON i.id = ei.item_id
             JOIN feeds f ON f.id = i.feed_id
             WHERE ei.event_id = ? ORDER BY i.published_at DESC`
          )
          .all(id) as Row[]
      ).map((i) => ({
        title: String(i.title),
        url: String(i.url),
        source: str(i.source) ?? str(i.feed),
        lang: str(i.lang),
        publishedAt: str(i.published_at),
      }));
      const dive = (
        db.prepare("SELECT * FROM dives WHERE event_id = ? ORDER BY id DESC LIMIT 1").all(id) as Row[]
      )[0];
      return {
        id,
        titleEn: String(e.title_en),
        titleJa: str(e.title_ja),
        riskScore: Number(e.risk_score),
        riskDirection: str(e.risk_direction) as BriefEvent["riskDirection"],
        tier: String(e.tier) as BriefEvent["tier"],
        why: str(e.why),
        thread: e.thread_slug
          ? { slug: String(e.thread_slug), name: String(e.thread_name) }
          : null,
        items,
        dive: diveRow(dive),
        audio: audioRow(
          (db
            .prepare("SELECT * FROM audio WHERE kind = 'dive' AND event_id = ?")
            .all(id) as Row[])[0]
        ),
      };
    });

    const rollup = audioRow(
      (db
        .prepare("SELECT * FROM audio WHERE brief_id = ? AND kind = 'rollup'")
        .all(briefId) as Row[])[0]
    );

    const market = (
      db
        .prepare("SELECT * FROM market_snapshots WHERE brief_id = ? ORDER BY id")
        .all(briefId) as Row[]
    ).map(marketRow);

    const dates = (
      db.prepare("SELECT date_jst FROM briefs ORDER BY date_jst DESC LIMIT 60").all() as Row[]
    ).map((r) => String(r.date_jst));

    const itemCount = Number(
      (db.prepare("SELECT COUNT(*) c FROM items").all()[0] as Row).c
    );

    const feedHealth = (
      db
        .prepare(
          "SELECT name, kind, last_status, last_fetch_at FROM feeds WHERE enabled = 1 ORDER BY kind, name"
        )
        .all() as Row[]
    ).map((r) => ({
      name: String(r.name),
      kind: String(r.kind),
      status: str(r.last_status),
      fetchedAt: str(r.last_fetch_at),
    }));

    return {
      id: briefId,
      dateJst: String(brief.date_jst),
      status: String(brief.status) as Brief["status"],
      startedAt: String(brief.started_at),
      publishedAt: str(brief.published_at),
      regimeNote: str(brief.regime_note),
      error: str(brief.error),
      market,
      events,
      rollup,
      dates,
      itemCount,
      feedHealth,
    };
  });
}

// ---------------------------------------------------------------- watchlist

const STATUS = new Set(["hold", "watch"]);
const BETA = new Set(["high", "mid", "low"]);

function watchRow(r: Row): WatchRow {
  return {
    id: Number(r.id),
    ticker: String(r.ticker),
    name: String(r.name),
    market: str(r.market),
    sector: str(r.sector),
    status: String(r.status) as WatchRow["status"],
    betaTag: String(r.beta_tag) as WatchRow["betaTag"],
    drivers: parseJson<string[]>(r.drivers_json, []),
    thesis: str(r.thesis),
  };
}

export function listWatchlist(): WatchRow[] {
  return withDb(true, (db) =>
    (db.prepare("SELECT * FROM watchlist ORDER BY status, ticker").all() as Row[]).map(watchRow)
  );
}

/** Throws on invalid input so the route can answer 400 rather than storing junk. */
function clean(f: Partial<WatchFields>): WatchFields {
  const ticker = (f.ticker ?? "").trim();
  const name = (f.name ?? "").trim();
  if (!ticker) throw new Error("ticker is required");
  if (!name) throw new Error("name is required");
  const status = STATUS.has(f.status ?? "") ? f.status! : "watch";
  const betaTag = BETA.has(f.betaTag ?? "") ? f.betaTag! : "mid";
  const drivers = (Array.isArray(f.drivers) ? f.drivers : [])
    .map((d) => String(d).trim())
    .filter(Boolean)
    .slice(0, 12);
  return {
    ticker,
    name,
    market: (f.market ?? "")?.toString().trim() || null,
    sector: (f.sector ?? "")?.toString().trim() || null,
    status,
    betaTag,
    drivers,
    thesis: (f.thesis ?? "")?.toString().trim() || null,
  };
}

export function upsertWatch(f: Partial<WatchFields>, id?: number): WatchRow {
  const v = clean(f);
  return withDb(false, (db) => {
    if (id) {
      db.prepare(
        `UPDATE watchlist SET ticker=?, name=?, market=?, sector=?, status=?, beta_tag=?,
         drivers_json=?, thesis=?, updated_at=? WHERE id=?`
      ).run(v.ticker, v.name, v.market, v.sector, v.status, v.betaTag,
            JSON.stringify(v.drivers), v.thesis, new Date().toISOString(), id);
    } else {
      db.prepare(
        `INSERT INTO watchlist(ticker,name,market,sector,status,beta_tag,drivers_json,thesis,updated_at)
         VALUES(?,?,?,?,?,?,?,?,?)
         ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, market=excluded.market,
           sector=excluded.sector, status=excluded.status, beta_tag=excluded.beta_tag,
           drivers_json=excluded.drivers_json, thesis=excluded.thesis,
           updated_at=excluded.updated_at`
      ).run(v.ticker, v.name, v.market, v.sector, v.status, v.betaTag,
            JSON.stringify(v.drivers), v.thesis, new Date().toISOString());
    }
    const row = db
      .prepare("SELECT * FROM watchlist WHERE ticker = ?")
      .all(v.ticker)[0] as Row;
    return watchRow(row);
  });
}

export function deleteWatch(id: number): boolean {
  return withDb(false, (db) => db.prepare("DELETE FROM watchlist WHERE id = ?").run(id).changes > 0);
}

export function getSettings(): { bookStyle: Record<string, string>; sectors: string[] } {
  return withDb(true, (db) => {
    const read = <T>(key: string, fallback: T): T => {
      const r = db.prepare("SELECT value FROM settings WHERE key = ?").all(key)[0] as Row | undefined;
      return r ? parseJson<T>(r.value, fallback) : fallback;
    };
    return {
      bookStyle: read("book_style", {
        long: "small-cap / high-beta Japanese equities",
        hedge: "short Nikkei 225 micro futures",
      }),
      sectors: read<string[]>("sectors_of_interest", []),
    };
  });
}

/** Patch semantics: only the keys actually supplied are written. Saving sectors alone must not
 *  blank the book style, which is what a replace-everything write did. */
export function saveSettings(patch: {
  bookStyle?: Record<string, string>;
  sectors?: string[];
}): void {
  withDb(false, (db) => {
    const put = db.prepare(
      "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    );
    if (patch.bookStyle && Object.keys(patch.bookStyle).length > 0) {
      put.run("book_style", JSON.stringify(patch.bookStyle));
    }
    if (Array.isArray(patch.sectors)) {
      put.run(
        "sectors_of_interest",
        JSON.stringify(patch.sectors.map((s) => String(s).trim()).filter(Boolean))
      );
    }
  });
}
