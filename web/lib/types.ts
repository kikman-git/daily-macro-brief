export type RiskDirection = "risk-on" | "risk-off" | "ambiguous";
export type DiveStatus = "researching" | "done" | "error";

export type Dive = {
  status: DiveStatus;
  model: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  verdict: RiskDirection | null;
  confidence: string | null;
  horizon: string | null;
  jpEquityDirection: string | null;
  highBetaNote: string | null;
  falsifier: string | null;
  bodyMd: string | null;
  sources: string[];
  error: string | null;
};

/** A rendered track. The file itself is served by /api/audio/[id], never by path. */
export type AudioTrack = {
  id: number;
  kind: "dive" | "rollup";
  status: "pending" | "done" | "error";
  durationS: number | null;
  bytes: number | null;
  error: string | null;
};

export type EventItem = {
  title: string;
  url: string;
  source: string | null;
  lang: string | null;
  publishedAt: string | null;
};

export type BriefEvent = {
  id: number;
  titleEn: string;
  titleJa: string | null;
  riskScore: number;
  riskDirection: RiskDirection | null;
  tier: "deep" | "thin";
  why: string | null;
  thread: { slug: string; name: string } | null;
  items: EventItem[];
  dive: Dive | null;
  audio: AudioTrack | null;
};

export type MarketRow = {
  symbol: string;
  label: string | null;
  last: number | null;
  chgPct: number | null;
  vsMa20Pct: number | null;
  vsMa50Pct: number | null;
  drawdownPct: number | null;
  realizedVolPct: number | null;
  error: string | null;
};

export type Brief = {
  id: number;
  dateJst: string;
  status: "pending" | "triaged" | "published" | "error";
  startedAt: string;
  publishedAt: string | null;
  regimeNote: string | null;
  error: string | null;
  market: MarketRow[];
  events: BriefEvent[];
  rollup: AudioTrack | null;
  dates: string[];
  itemCount: number;
  feedHealth: { name: string; kind: string; status: string | null; fetchedAt: string | null }[];
};

export type WatchRow = {
  id: number;
  ticker: string;
  name: string;
  market: string | null;
  sector: string | null;
  status: "hold" | "watch";
  betaTag: "high" | "mid" | "low";
  drivers: string[];
  thesis: string | null;
};

export type WatchFields = Omit<WatchRow, "id">;

/** One run of scripts/tickers.py — the weekly timer, the dashboard button, or a shell. `stalled`
 *  is derived on read: a run whose process died stays 'running' until the next run reaps it. */
export type SyncRun = {
  id: number;
  trigger: string;
  phase: string;
  status: "running" | "ok" | "error" | "skipped";
  startedAt: string;
  finishedAt: string | null;
  asof: string | null;
  rowsSeen: number | null;
  added: number | null;
  changed: number | null;
  delisted: number | null;
  namesAdded: number | null;
  error: string | null;
  stalled: boolean;
};

/** One ranked match from the JPX ticker mirror. `betaHint` is a suggestion from JPX's size
 *  classification, not a measurement — the form pre-selects it and the user overrides. */
export type TickerHit = {
  code: string;
  nameJa: string;
  nameEn: string | null;
  market: string;
  kind: string;
  sector: string | null;
  sector17: string | null;
  scale: string | null;
  betaHint: "high" | "mid" | "low";
  score: number;
};
