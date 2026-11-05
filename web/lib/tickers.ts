/** Fuzzy ticker search over the local JPX mirror (`tickers`, written by scripts/tickers.py).
 *
 *  Runs server-side against an index built once per process rather than shipping 4,400 rows to
 *  the browser: each keystroke is then an in-memory scan (~1ms) and the wire carries only the
 *  dozen rows shown. The alternative — download the universe, score in the client — trades a
 *  ~450KB first load for saving a localhost round trip we don't feel.
 *
 *  Matching has to survive how a person actually types a Japanese ticker:
 *    "6920" / "6920.T"  → the code, with or without the Yahoo suffix
 *    "レーザー" / "れーざー" → kana, either script, long marks optional
 *    "rezateku"          → romaji of the kana name
 *    "lasertec"          → the English name, when the Yahoo backfill has run
 *    "toyot"             → a prefix; "tyota" → a typo (bigram similarity, ≥4 chars only)
 */
import { DatabaseSync } from "node:sqlite";
import os from "node:os";
import path from "node:path";
import type { SyncRun, TickerHit } from "./types";

const DB_PATH =
  process.env.DAILY_FEEDS_DB ?? path.join(os.homedir(), ".openclaw/data/daily-feeds.sqlite");
/** The mirror changes when JPX republishes (monthly), so a process-lifetime cache with a
 *  coarse TTL is plenty — and a cold index costs one 4,400-row read. */
const TTL_MS = 5 * 60 * 1000;
/** Below this a hit is a coincidence, and coincidences are worse than an empty list: they are
 *  what fills the dropdown precisely when the right answer isn't in the mirror, and the row you
 *  want to click then is "enter it by hand". A one-letter substitution still clears it. */
const MIN_SCORE = 250;

type Row = {
  code: string;
  nameJa: string;
  nameEn: string | null;
  market: string;
  kind: string;
  sector33: string | null;
  sector17: string | null;
  scale: string | null;
};

/** A row plus its folded haystacks. `w` is a fixed penalty, not a multiplier: a code hit must
 *  beat a name hit of the same shape, and a romaji hit is the weakest evidence of the four.
 *  `loose` allows the fuzzy tiers — see scoreOne. */
type Indexed = Row & { hay: { s: string; w: number; loose: boolean }[]; equity: boolean };

type Index = { rows: Indexed[]; asof: string | null; withEnglish: number; builtAt: number };

let cache: Index | null = null;

/** NFKC (full-width ＴＯＰＩＸ → TOPIX), lowercase, hiragana → katakana, and drop the
 *  characters people leave out or add at random: spaces, punctuation, the long-vowel mark. */
export function fold(s: string): string {
  const n = s.normalize("NFKC").toLowerCase();
  let out = "";
  for (const c of n) {
    const cp = c.codePointAt(0)!;
    if (cp >= 0x3041 && cp <= 0x3096) {
      out += String.fromCodePoint(cp + 0x60); // hiragana → katakana
    } else if ("ー-–—‐・･/／\\,，.。()（）「」『』【】〔〕&＆'’\"”|｜:：;；*＊_＋+ 　\t".includes(c)) {
      continue;
    } else {
      out += c;
    }
  }
  return out;
}

/** Corporate suffixes, longest first, as they look *after* fold() has removed spaces and dots. */
const SUFFIXES = [
  "companylimited",
  "incorporated",
  "corporation",
  "holdings",
  "company",
  "limited",
  "coltd",
  "corp",
  "ltd",
  "inc",
  "kk",
];

/** "laserteccorporation" → "lasertec". Indexed *alongside* the full name, never instead of it.
 *
 *  The suffix is dead weight for every fuzzy comparison: "lasertek" scores 0.48 against
 *  "laserteccorporation" — under the typo threshold purely because eleven characters of
 *  "corporation" dilute the bigram overlap — and 0.86 against the stem. */
function stripSuffixes(s: string): string {
  let out = s;
  for (let again = true; again; ) {
    again = false;
    for (const suf of SUFFIXES) {
      if (out.length > suf.length + 2 && out.endsWith(suf)) {
        out = out.slice(0, -suf.length);
        again = true;
        break;
      }
    }
  }
  return out;
}

function buildIndex(): Index {
  const db = new DatabaseSync(DB_PATH, { readOnly: true });
  db.exec("PRAGMA busy_timeout = 5000"); // a WAL checkpoint mid-sync must not empty the picker
  try {
    const raw = db
      .prepare(
        `SELECT code, name_ja, name_en, romaji, market, kind, sector33, sector17, scale, asof
           FROM tickers`
      )
      .all() as Record<string, string | null>[];
    let withEnglish = 0;
    let asof: string | null = null;
    const rows = raw.map((r) => {
      const nameEn = r.name_en ?? null;
      if (nameEn) withEnglish++;
      if (r.asof && (!asof || r.asof > asof)) asof = r.asof;
      const code = String(r.code);
      const nameJa = String(r.name_ja);
      const en = nameEn ? fold(nameEn) : null;
      const stem = en ? stripSuffixes(en) : null;
      const hay = [
        { s: code.toLowerCase(), w: 0, loose: false },
        { s: fold(nameJa), w: 12, loose: true },
        ...(en ? [{ s: en, w: 24, loose: true }] : []),
        ...(stem && stem !== en ? [{ s: stem, w: 24, loose: true }] : []),
        // romaji ships as space-separated variants ("rezatekku rezateku") — one haystack each.
        ...(r.romaji
          ? r.romaji.split(" ").filter(Boolean).map((s) => ({ s, w: 36, loose: true }))
          : []),
      ];
      return {
        code,
        nameJa,
        nameEn,
        market: String(r.market),
        kind: String(r.kind),
        sector33: r.sector33 ?? null,
        sector17: r.sector17 ?? null,
        scale: r.scale ?? null,
        hay,
        equity: r.kind === "equity",
      };
    });
    return { rows, asof, withEnglish, builtAt: Date.now() };
  } finally {
    db.close();
  }
}

/** Null when the mirror hasn't been synced yet (fresh box, or the table predates this feature) —
 *  the picker then degrades to plain manual entry rather than erroring. */
function index(): Index | null {
  if (cache && Date.now() - cache.builtAt < TTL_MS) return cache;
  try {
    cache = buildIndex();
    return cache;
  } catch {
    cache = null;
    return null;
  }
}

/** Every character of `q` appears in `h`, in order — the tier that survives a dropped character
 *  ("sofbank" → ソフトバンク's romaji sofutobanku). Returns the span it consumed, or 0 for no match.
 *
 *  The span is what makes this tier usable rather than embarrassing: unbounded, "lasertec"
 *  matches 岐阜造園 (gifu**l**and**s**c**a**p**e**…) by scattering eight letters across 23, and
 *  since nothing else matched, that garbage was the top hit. Requiring the match to stay tight
 *  turns those into an honest "no listing matched" — which is the answer.
 *
 *  Greedy from the first matching character, so the span is an upper bound, not the minimum: a
 *  tighter window later in the string is missed. That errs toward rejecting, and a tight window
 *  that is also contiguous is already caught by the higher-scoring substring tier above.
 */
function subsequenceSpan(q: string, h: string): number {
  let i = 0;
  let first = -1;
  for (let j = 0; j < h.length; j++) {
    if (h[j] === q[i]) {
      if (first < 0) first = j;
      if (++i === q.length) return j - first + 1;
    }
  }
  return 0;
}

/** Dice coefficient over character bigrams — cheap typo tolerance ("tyota" ≈ "toyota"). */
function dice(q: string, h: string): number {
  if (q.length < 2 || h.length < 2) return 0;
  const grams = new Map<string, number>();
  for (let i = 0; i < q.length - 1; i++) {
    const g = q.slice(i, i + 2);
    grams.set(g, (grams.get(g) ?? 0) + 1);
  }
  let hit = 0;
  for (let i = 0; i < h.length - 1; i++) {
    const g = h.slice(i, i + 2);
    const n = grams.get(g);
    if (n) {
      hit++;
      grams.set(g, n - 1);
    }
  }
  return (2 * hit) / (q.length - 1 + h.length - 1);
}

/** `loose` enables the fuzzy tiers. Codes are excluded from them: a 4-character haystack
 *  subsequence-matches half the exchange (typing 6920 surfaced 3692, 3920, 4920…), and the
 *  digits of a ticker are not a string a typo model has anything useful to say about. */
function scoreOne(q: string, h: string, loose: boolean): number {
  if (h === q) return 1000;
  if (h.startsWith(q)) return 880 - Math.min(30, h.length - q.length);
  const at = h.indexOf(q);
  // No word-boundary bonus: fold() has already removed the spaces and punctuation it would
  // key off, and the Japanese names — the bulk of the corpus — never had any.
  if (at >= 0) return 620 - Math.min(30, at);
  if (!loose) return 0;
  if (q.length >= 3) {
    // Density, not a fixed skip allowance: the query must make up most of the span it matched
    // across. A flat "up to 3 skipped characters" reads as a typo at ten characters and as a
    // coincidence at four — it let "sony" match カワセコンピュータサプライ (kawa**s**ek**on**p**y**u…)
    // while the real ソニーグループ had no English name yet to beat it.
    const span = subsequenceSpan(q, h);
    const density = span ? q.length / span : 0;
    if (density >= 0.6) return 380 + Math.round(60 * density);
  }
  if (q.length >= 4) {
    const d = dice(q, h);
    if (d >= 0.5) return Math.round(300 * d);
  }
  return 0;
}

/** Codes get typed with the baggage of whatever chart they were copied from: `6920.T`,
 *  `6920.TO`, `TSE:6920`. Stripped before fold(), which would eat the dot and leave `6920t`. */
function stripCodeNoise(q: string): string {
  return q.replace(/^(?:tse|jpx?|tyo)\s*[:.]\s*/, "").replace(/\.t(?:o|se)?$/, "");
}

/** Tie-break by JPX's own size class. Not a preference for large caps — it decides which name a
 *  bare string most likely meant: "トヨタ" prefix-matches both トヨタ自動車 and トヨタ紡織, and
 *  shortest-name-wins picked the wrong one. Capped small enough that it can only reorder
 *  near-ties, never lift a fuzzy match over a prefix hit. */
function sizeBonus(scale: string | null): number {
  switch (scale) {
    case "TOPIX Core30":
      return 25;
    case "TOPIX Large70":
      return 18;
    case "TOPIX Mid400":
      return 12;
    case "TOPIX Small 1":
      return 6;
    case "TOPIX Small 2":
      return 3;
    default:
      return 0;
  }
}

export type TickerSearch = {
  hits: TickerHit[];
  total: number;
  asof: string | null;
  withEnglish: number;
  /** false = the mirror is missing/empty; the caller should fall back to manual entry. */
  ready: boolean;
};

export function searchTickers(query: string, limit = 12): TickerSearch {
  const idx = index();
  const base = {
    total: idx?.rows.length ?? 0,
    asof: idx?.asof ?? null,
    withEnglish: idx?.withEnglish ?? 0,
    ready: (idx?.rows.length ?? 0) > 0,
  };
  const q = fold(stripCodeNoise(query.trim().toLowerCase()));
  if (!idx || !q) return { hits: [], ...base };

  const scored: { row: Indexed; score: number }[] = [];
  for (const row of idx.rows) {
    let best = 0;
    for (const { s, w, loose } of row.hay) {
      const v = scoreOne(q, s, loose);
      if (v > 0 && v - w > best) best = v - w;
    }
    if (best <= 0) continue;
    // Nudges, never reorderings: a real company outranks an ETF tracking it, and a PRO Market
    // shell (no liquidity, not investable here) sinks below both.
    if (row.equity) best += 30;
    if (row.market === "TSE PRO") best -= 60;
    best += sizeBonus(row.scale);
    if (best >= MIN_SCORE) scored.push({ row, score: best });
  }
  scored.sort((a, b) => b.score - a.score || a.row.code.localeCompare(b.row.code));

  return {
    hits: scored.slice(0, limit).map(({ row, score }) => ({
      code: row.code,
      nameJa: row.nameJa,
      nameEn: row.nameEn,
      market: row.market,
      kind: row.kind,
      sector: row.sector33,
      sector17: row.sector17,
      scale: row.scale,
      betaHint: betaHint(row),
      score,
    })),
    ...base,
  };
}

/** Mirror state without running a search — what the panel's header line reports. */
export function mirrorStatus(): { total: number; asof: string | null; withEnglish: number } {
  const idx = index();
  return {
    total: idx?.rows.length ?? 0,
    asof: idx?.asof ?? null,
    withEnglish: idx?.withEnglish ?? 0,
  };
}

/** Recent runs of scripts/tickers.py, newest first.
 *
 *  `stalled` is derived here rather than stored: only the Python side writes this table (the UI
 *  writes nothing but watchlist and settings), so a run whose process died stays 'running' until
 *  the next run reaps it. Showing it as "stalled" past the same 30-minute mark the script uses
 *  keeps a dead run from reading as a live one in the meantime.
 */
export function listSyncs(limit = 12): SyncRun[] {
  let db;
  try {
    db = new DatabaseSync(DB_PATH, { readOnly: true });
  } catch {
    return [];
  }
  try {
    db.exec("PRAGMA busy_timeout = 5000");
    const rows = db
      .prepare(
        `SELECT id, trigger, phase, status, started_at, finished_at, asof, rows_seen,
                added, changed, delisted, names_added, error
           FROM ticker_syncs ORDER BY started_at DESC LIMIT ?`
      )
      .all(limit) as Record<string, string | number | null>[];
    const staleBefore = Date.now() - 30 * 60 * 1000;
    return rows.map((r) => ({
      id: Number(r.id),
      trigger: String(r.trigger),
      phase: String(r.phase),
      status: String(r.status) as SyncRun["status"],
      startedAt: String(r.started_at),
      finishedAt: r.finished_at ? String(r.finished_at) : null,
      asof: r.asof ? String(r.asof) : null,
      rowsSeen: r.rows_seen == null ? null : Number(r.rows_seen),
      added: r.added == null ? null : Number(r.added),
      changed: r.changed == null ? null : Number(r.changed),
      delisted: r.delisted == null ? null : Number(r.delisted),
      namesAdded: r.names_added == null ? null : Number(r.names_added),
      error: r.error ? String(r.error) : null,
      stalled:
        r.status === "running" && Date.parse(String(r.started_at)) < staleBefore,
    }));
  } catch {
    // Table absent on a box that has never synced — an empty history, not an error page.
    return [];
  } finally {
    db.close();
  }
}

/** A *suggested* beta bucket from JPX's own size classification — TOPIX scale where there is
 *  one, market otherwise. Growth has no scale code and is high-beta by construction; the
 *  large-cap buckets are the names that move with the index rather than ahead of it. The
 *  form pre-selects this and the user overrides it; nothing downstream trusts it. */
function betaHint(row: { scale: string | null; market: string }): "high" | "mid" | "low" {
  const s = row.scale ?? "";
  if (s === "TOPIX Core30" || s === "TOPIX Large70") return "low";
  if (s === "TOPIX Mid400") return "mid";
  if (s.startsWith("TOPIX Small")) return "high";
  return row.market === "TSE Growth" ? "high" : "mid";
}
