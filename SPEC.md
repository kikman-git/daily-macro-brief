# daily-feeds — SPEC (decisions of record)

Personal macro-news feed for a Japanese equities trader. Replaces the *analytical* function of
a nikkei.com subscription using only free sources, and removes the Google-Translate step.

Drafted 2026-08-04 from a design interview. **Not yet implemented.**

## 1. What this is (and is not)

**Is:** a 07:00 JST pre-open **causal analysis** brief. For the 2–3 events most likely to flip
the market risk-on/risk-off, it explains mechanism, motive, second-order effects, and
transmission into Japanese equities — with explicit attention to **small-cap high-beta**.

**Is not:** a headline digest, and not a position-management system. The model judges whether
an **event** is a risk-on or risk-off catalyst. **The reader makes every position call.**

### Honest limits (accepted, not to be re-litigated)
- **Nikkei scoops (観測記事) cannot be replaced.** A free pipeline cannot pre-report M&A or
  guidance leaks. If scoops are the binding reason to keep the subscription, keep it — this
  tool targets the other three functions.
- **Consensus-vs-actual for economic releases has no free RSS source.** Investing.com JP is the
  closest and is thin. Treated as a known gap, not silently faked.
- **Nikkei VI (`^NKVI`) is unavailable** on the free Yahoo endpoint. JP vol is proxied by
  realized vol on Growth250 plus `^VIX`.
- **Prediction markets give a thin Fed signal and no usable BOJ signal** — but not for the
  reason first assumed. Kalshi *does* list a well-shaped BOJ market (`KXCBDECISIONJAPAN`, live
  Sep-2026 event, outcomes maintain/±25bp/>±25bp), yet exposes **no prices unauthenticated**
  (0/1000 open markets carry last/bid/volume) and that book is empty with zero trades.
  Polymarket *does* serve prices but its macro coverage is one usable Fed contract.
  So: quote Polymarket's Fed contract; for the BOJ use JGB/OIS + analyst consensus, labelled a
  proxy, and never present it as a market price. See `SOURCES.md` §F. A free Kalshi API key is
  the highest-value v2 upgrade here.

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **v1 = one 07:00 JST pre-open brief.** Weekly thematic deferred to v2. | Anchor artifact; covers overnight US + night session before the 09:00 open. |
| 2 | **Tiered depth: 2–3 deep dives + one-line tail.** | ~100 items/day; full treatment on each is unreadable and unaffordable. |
| 3 | **Dives selected by risk-on/risk-off potential**, not general newsworthiness. | The reader's stated filter. Directly serves the cut/hold decision on a high-beta book. |
| 4 | **Hard relevance floor. Zero dives is a valid outcome.** | Prevents manufacturing significance on quiet days — the standard failure of daily briefs. |
| 5 | **LLM judges events; code owns the numbers.** Market figures are computed in Python and handed to the model in the prompt — never recalled from memory. | The model may reason freely; it must not be able to invent that Growth250 is −3% when it is −0.4%. |
| 6 | **Universe = a watchlist the reader maintains in the dashboard** (`watchlist` + `settings` tables). `config/watchlist.example.json` is now only a schema reference. | Enables name-level transmission. Editing it in the UI beats hand-editing JSON over SSH, and it makes the DB the single source of truth for both the dive prompt and the reader. |
| 7 | **Delivery = Next.js dashboard `127.0.0.1:18793` → tailscale `:8446`, plus SQLite archive.** No email, no Telegram. | Same pattern as ledger-web/human-graph/myself. Web enables drill-down + incremental publish. |
| 8 | **Standalone repo. Do NOT reuse `blogwatcher`. Do NOT extend the `news-*` skills.** | `blogwatcher` has no namespacing — one global feed list and one global read/unread state, so `read-all` here would destroy the `news-synthesizer` pipeline's state. Its relevance logic is ~80% wrong for trading. |
| 9 | **Python ingest + `claude -p` analysis + systemd timer.** | Deterministic, unit-testable, and analysis can be re-run on cached articles without re-fetching — essential for prompt iteration. |
| 10 | **Research budget: pre-assembled bundle + bounded live search, up to 30 min per dive.** | "Why jointly / what's the US motive / what do betting markets say" is not in the RSS text. |
| 11 | **Dives run in parallel (cap 3) with incremental publish.** | Wall-clock = slowest dive, not the sum. Permanently fixes the DST window problem (§3). |
| 12 | **Sonnet triage, Opus dives. Each dive = a fresh session loading a specialized skill.** | Cheap work stays cheap; fresh session prevents cross-contamination; the skill pins a consistent causal framework. |
| 13 | **Sonnet clusters items into *events* semantically before triage.** | String dedup cannot match `日米協調介入` to "joint US-Japan intervention". Cross-language dedup requires semantics. |
| 14 | **Persistent theme threads.** Each dive receives the prior 3–5 entries on its thread. | This continuity *is* the "interconnected implication" goal. Lets a dive say "third intervention signal in 6 weeks, second one failed to hold." |
| 15 | **Output English, JP financial terms preserved** (日銀 / 円安 / 上方修正), every item links its original source. | The stated reason for building this was the translation tax. |
| 16 | **The watchlist picker searches a local mirror of JPX's 東証上場銘柄一覧** (`tickers`), with English names as an optional Yahoo backfill. | Decision 6 made the UI the way positions get entered, and four hand-typed fields per name was the friction. JPX is the authority on what is listed, so a local copy needs no symbol API and no per-keystroke network call. |
| 17 | **The mirror refreshes on its own weekly timer** (`daily-feeds-tickers.timer`, Mondays 20:00 UTC), *not* as a stage of `run.py`, and every run is recorded in `ticker_syncs` and surfaced on `/watchlist`. | A fetch inside the 06:10 JST path is a new way for the brief to fail, and 20:00 UTC keeps the two off the same SQLite file. Recording each run is the point of putting a dataset on a schedule at all: the failure mode of an invisible cron job is silently stale data, so "last run, what changed, what broke" has to be readable from the dashboard. The unit is templated on its trigger so the button and the timer are one code path with two labels. |

## 3. Scheduling — the DST trap

| | US cash close | Window to 07:00 JST |
|---|---|---|
| Summer (EDT) | 05:00 JST | ~1h45m |
| Winter (EST) | 06:00 JST | **~45 min** |

Sequential 30-min dives (×3 = 90 min) blow the winter window. Resolved by decision 11:
**timer at 21:10 UTC**, regime + thin items publish ~5 min in, each dive appears as it lands
marked `researching…`. Reading can start before analysis completes.

## 4. Pipeline

```
21:10 UTC (06:10 JST) systemd timer -> run.py
  0. preflight    prove claude-cli can complete a turn before committing
  1. fetch.py     27 feeds -> SQLite raw items, dedupe by URL, 48h date gate
  2. market.py    Yahoo chart API -> computed snapshot (see §5)
  3. prefilter.py ~730 in-window items -> 140, deterministic (see §4a)
  4. triage.py    claude -p --model sonnet
                    cluster items -> events (cross-language)
                    score risk-on/off potential, assign threads, translate titles
                    -> ranked events JSON
     PUBLISH regime + thin tail immediately
  5. dive.py      top N<=3 above floor, PARALLEL, fresh session each,
                  claude -p --model opus, skill: macro-dive,
                  bundle + WebSearch/WebFetch + Polymarket/Kalshi, 30 min cap
     PUBLISH each dive on completion (row goes to 'researching' before the call)
  6. speech.py    one .m4a per dive + a roll-up, local Piper TTS (see §4b)
                  NON-FATAL: the brief has already published by here
```

### 4b. Audio (added during implementation)

A dive is 900–1,600 words ≈ 5–7 minutes aloud, which is the length of the walk to a desk. Each
dive gets a track; the whole morning gets a roll-up assembled from those tracks.

**Engine: local Piper, not the Gemini API.** Gemini TTS was the first choice and it works, but
the quota on this project's key is `GenerateRequestsPerDayPerProjectPerModel-FreeTier = 10
requests/day` for `gemini-2.5-flash-preview-tts`. One brief needs ~40 calls, so the API path
cannot render a single complete morning without billing. Piper runs on CPU with no quota, which
is the only property that matters for something that must work unattended at 06:10 every day.
`--engine gemini` stays wired and correct — a one-word switch if billing is ever enabled.

| | Piper (`en_US-ryan-high`) | Gemini (`2.5-flash-preview-tts`) |
|---|---|---|
| Quota | none | **10 requests/day** (free tier) |
| Speed | ~2× realtime, 22.05 kHz | ~2× realtime, 24 kHz |
| Japanese | no — see gloss below | yes |
| Per-call input limit | none | **<2,000 chars**; 2,000 returns `finishReason=OTHER`, zero output, no error |

Measured on the live key before the quota was hit: 600 chars → 30s audio, 1,200 chars → 47s,
2,000 chars → nothing. That is why `GEMINI_CHUNK = 1100` with a halve-and-retry, while
`PIPER_CHUNK = 4000` is sized only for parallelism.

**The dive body is never fed to a synthesiser raw.** It carries markdown tables, citation URLs
and emphasis marks; read literally that yields "h-t-t-p-s colon slash slash". `speechify()`
drops URLs, keeps link text, verbalises ≤3-column tables row by row and hands wider ones back
to the page, and turns the committed frontmatter into a spoken lede. `speech.py --dry-run`
prints the exact script and reports URL / table-pipe / unspoken-CJK leakage without
synthesising anything.

**Cost of going local: Japanese.** Piper voices are monolingual. Measured on a real dive, CJK is
0.5% of the spoken script (25 short runs), so `JA_GLOSS` translates the recurring macro
vocabulary (日銀, 円安, 協調介入, 財務官 …) and the remainder is dropped. Safe in practice because
the dives gloss their own Japanese inline — `円買い介入 (yen-buying intervention)` — and a
dedupe rule collapses the resulting `X (X)` stutter. **Personal names are lost**: transliterating
them needs a dictionary this stage has no business carrying.

The roll-up concatenates the PCM already rendered for each dive behind a short spoken title,
so it costs one intro call plus one title per event rather than a second pass over every word.
Output is AAC in `.m4a` — the one codec every phone browser plays, iOS Safari included — with
`+faststart` so the player can seek before the file finishes loading.

### 4a. Why a prefilter stage exists (added during implementation)

Handing triage 260 of the day's ~730 in-window items **timed out at 15 minutes** — on its own
that blows the winter pre-open window. But the volume is not information: adapter feeds are
dominated by template-shaped filler and official feeds carry daily administrative noise.
`prefilter.py` drops by headline *format* (never by topic), collapses syndicated duplicates,
then keeps the top 140 by priority with a guaranteed JP/US split.

Two findings worth keeping:
- **One Reuters Fed story appeared 9 times** under different local TV affiliates, identical but
  for the ` - WPDE` / ` - KTUL` suffix. Dedup must strip the publisher suffix *before*
  truncating, or every copy hashes differently and the whole cluster survives.
- **"Official source" is not a proxy for relevance.** Exempting official feeds from filtering
  admitted stewardship-code lists and a BOJ paper on optical quantum computing while a JGB
  auction tail competed for budget. Priority is scored on macro vocabulary × source class, so a
  BOJ statement on rates outranks a BOJ paper on photonics.

`claude -p` latency here is **not** a function of prompt size alone: every Claude agent on this
box shares one OAuth credential and one rate-limit pool, so an identical call ranges from ~2 to
~20 minutes. Triage therefore retries with a progressively smaller payload (140 → 70 → 40)
rather than failing the morning.

Preflight: assert claude-cli OAuth is live before starting. The token is ~8h and the 21:10 UTC
run lands after a daytime token expires, so it depends on unattended refresh-token rotation.
**Auth failure must surface as a visible broken state on the dashboard, never a silent
no-brief morning.**

## 5. Computed market snapshot (handed to the model, not recalled)

Free Yahoo chart API, no key: `^N225`, `1305.T` (TOPIX), **`2516.T` (東証グロース250 — the
high-beta proxy)**, `JPY=X`, `^VIX`, `^SOX` (semis, dominant for JP high-beta), `^GSPC`.
Derived: overnight % change, distance from MA20/MA50, drawdown from N-day high, realized vol.

## 6. Deep-dive structure (the `macro-dive` skill)

Every dive answers the same questions — drawn from the reader's worked example (the US–JP joint FX
intervention):

1. What happened — facts only, each sourced
2. Why now, and why in this form (e.g. why *jointly*)
3. Cui bono — who benefits, including non-obvious parties (e.g. the US motive in a JPY problem)
4. Second-order effects
5. Transmission to **JP equities** — exporters vs domestics, large vs small cap, high-beta specifically
6. Transmission to **US equities**
7. Policy path — what this implies for BOJ and Fed
8. Market-implied odds — Polymarket/Kalshi where liquid; JGB/OIS + consensus for BOJ, labelled
9. Thread context — how this fits the ongoing theme, what changed since last time
10. **Verdict: risk-on / risk-off / ambiguous, with confidence**
11. **What would falsify this read**
12. Watchlist impact — named tickers from `config/watchlist.json`

## 7. Schema (SQLite)

`~/.openclaw/data/daily-feeds.sqlite`, WAL mode (the Next.js reader holds a read-only handle
open while the Python stages write). Canonical definition: `scripts/db.py`.

```
briefs(id, date_jst UNIQUE, status, started_at, published_at, regime_note, error)
feeds(id, name, url UNIQUE, kind, lang, enabled, last_fetch_at, last_status)
items(id, feed_id, url UNIQUE, title, title_en, source, published_at, fetched_at, summary, lang)
threads(id, slug UNIQUE, name, created_at, last_seen_at, summary)
events(id, brief_id, title_en, title_ja, risk_score, risk_direction, tier, rank, why,
       thread_id, query_ja, query_en)
event_items(event_id, item_id)
dives(id, event_id, status, model, started_at, finished_at, verdict, confidence, horizon,
      jp_equity_direction, high_beta_note, falsifier, body_md, sources_json, error)
market_snapshots(id, brief_id, symbol, label, last, chg_pct, extras_json, asof)
watchlist(id, ticker UNIQUE, name, market, sector, status, beta_tag, drivers_json, thesis,
          updated_at)
tickers(code PK, name_ja, name_en, romaji, market, kind, sector33, sector17, scale, asof,
        updated_at)                       -- JPX mirror; the picker's search corpus
ticker_syncs(id, trigger, phase, status, started_at, finished_at, asof, rows_seen, added,
             changed, delisted, names_added, error)   -- one row per mirror refresh
audio(id, brief_id, event_id NULL, kind, status, path, bytes, duration_s, chars, chunks,
      model, voice, script_txt, created_at, error)
  UNIQUE INDEX audio_slot ON (brief_id, kind, COALESCE(event_id, -1))
settings(key, value)                      -- book_style, sectors_of_interest,
                                          -- tts_engine, tts_voice
```

`audio` is its own table rather than columns on `dives`: the roll-up belongs to no single event,
and re-synthesising audio must never be able to touch dive text. `event_id` NULL marks the
roll-up, which is why the unique index uses `COALESCE(event_id, -1)` — SQLite treats NULLs as
distinct, so a plain `UNIQUE(brief_id, kind, event_id)` would insert a fresh roll-up every run.
`script_txt` stores exactly what was spoken, so a bad reading can be diagnosed without
re-running the synthesiser. Files live beside the DB in
`~/.openclaw/data/daily-feeds-audio/<date>/`, following the `myself-media` convention.

Added during implementation, beyond the original sketch: `briefs.error` and `dives.error` so a
failure is a *visible* state rather than an absence; `events.why`/`rank`; `events.query_ja/_en`
so triage authors the search queries its own dive will use; `feeds.last_status` to drive the
feed-health line on the dashboard; and `watchlist`/`settings` per decision 6.

`tickers` is reference data, not pipeline state — the only table nothing in the daily run reads
or writes. It carries three name columns because they answer different queries: `name_ja` is
JPX's own string (complete, authoritative), `romaji` is derived locally from the kana so a
latin-typed query reaches the 3,107 of 4,444 listings whose name carries any kana, and
`name_en` is the
optional Yahoo backfill that reaches the rest — a kanji name has no local reading, so without
it "nintendo" cannot find 任天堂. A `--sync` never overwrites `name_en`; JPX has no such column
to overwrite it with.

`dives` retains verdict + inputs so the model's risk-on/off calls accumulate an auditable
track record over months.

## 8. Verified sources

See `SOURCES.md` — every feed HTTP-tested 2026-08-04 with item counts, including which ones
failed and why.

Key finding: **Google News RSS is a universal adapter.** `hl=ja&gl=JP&ceid=JP:ja` with a
`site:` filter yields ~100 items for sources that publish no RSS at all — this is how
**kabutan** (no RSS) and **Reuters Japan** (direct feed 404s) are reached.

## 9. Open items

- [ ] **Watchlist contents** — needs the reader's actual small-cap/high-beta names, entered at
      `:8446/watchlist`. Blocks name-level transmission only; everything else works without it,
      and dives correctly fall back to sector + Growth250 beta rather than inventing tickers.
- [ ] **Relevance floor (55) and prefilter budget (140) need tuning against ~2 weeks of real
      output.** Both are first guesses. The floor decides how often "nothing cleared it" is the
      honest answer; the budget trades coverage against triage wall-clock.
- [ ] **Two proper nouns are mispronounced and have no verified fix: `Nikkei` → "Nik", `TOPIX`
      → "topics".** Both still parse in context, so they are cosmetic, but Nikkei is the most
      frequent word in the brief and worth another attempt.
      **Method, learned the hard way:** a respelling must be verified *in a real dive sentence*,
      not in an isolated probe. `Nikkay` transcribed back perfectly as "The Nikkay 225 closed
      higher" and still produced "Nik 225" inside the actual paragraph — Piper's phonemisation is
      context-sensitive. It was reverted rather than shipped, because a respelling that does not
      demonstrably help just puts a misspelling into `script_txt`.
      `SAY_AS` therefore holds only ordinary-English expansions, which cannot be mispronounced
      the same way (`TSE` → "Tokyo Stock Exchange", which fixed a real "TSC").
      Verification needs the Gemini transcription quota, which is on the same rate-limited free
      key as everything else here.
- [ ] **`JA_GLOSS` will need terms added as new themes appear.** It covers the recurring macro
      vocabulary; anything unmatched is silently dropped from the spoken track (never from the
      page). `speech.py --dry-run` reports unspoken-CJK leakage, so drift is detectable — check
      it when a new theme starts recurring. Personal names are always lost; transliteration
      needs a dictionary this stage should not carry.
- [ ] **Whether 33 minutes is the right roll-up length.** It is simply the sum of the dives at
      ~145 wpm. If it proves too long to use, the fix is a separate short-form script per dive
      rather than speeding up the read.
- [x] ~~**Dive length overruns**~~ — measured at 2,176 (spike) and 2,006 / 2,126 / 2,303 (first
      real run) against a 900–1,600 target. Fixed with hard per-section word caps in the skill plus
      an automated check in `dive.py audit()`. **Verified:** a validation dive with the capped text
      came in at 1,321 words, 0/12 sections over cap, audit clean — and denser, not thinner.
- [x] ~~A false quiet day is reachable by accident~~ — `dive.py --event` derived its brief from
      the clock, so a run past midnight JST created and published an empty brief for the next day,
      which the dashboard rendered as "nothing cleared the relevance floor". Fixed at the root and
      guarded in the reader (prefer the newest brief holding a market snapshot). **This is the
      failure mode to keep testing for:** an empty brief must always be distinguishable from a
      quiet market, and `status='published'` with zero market rows is the signature of a fake one.
- [x] ~~A cited number is not a verified number~~ — two dives disagreed on the same Nikkei close
      (63,445.53/−1.4% vs the correct 63,754.90/−0.94%) because one cited an aggregator that had
      it wrong. Fixed structurally: `market_snapshot` now carries `recent_closes` (last five
      dated sessions), so a dive never needs to fetch a recent close. Worth remembering as a
      class of error — citation discipline proves provenance, not accuracy.
- [ ] No push notification: the dashboard is pull-only, so nothing tells the reader the brief is
      ready. A one-line Telegram ping is cheap if wanted.
- [ ] Watch whether the 21:10 UTC run is materially faster than interactive testing. Latency
      during development was inflated by competing for the shared rate-limit pool with the very
      session doing the development; the timer runs when the box is otherwise idle.
- [x] ~~Add `:8446` to `/home/ubuntu/bin/tailscale-serve-apps.sh`~~ — done, else the mapping
      dies on every gateway restart.
- [ ] v2 candidates: free Kalshi API key (unlocks real Fed *and* BOJ probabilities — highest
      value); weekly thematic brief; cross-thread causality graph; event-triggered alerts
      (BOJ/FOMC/CPI); e-Stat API for JP official statistics.
