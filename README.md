# daily-macro-brief

A 07:00 JST pre-open **causal analysis** brief for Japanese equities, built for a discretionary small-cap / high-beta trader to replace the analytical function of a nikkei.com subscription using only free sources, and to remove the Google-Translate step on Japanese articles. It is not a headline digest: for the 2–3 events most likely to flip the market risk-on/risk-off it explains mechanism, motive, second-order effects and transmission into Japanese equities, with specific attention to **small-cap high-beta**. **The model judges events. You judge positions.** Nothing here sizes or times a trade. Decisions of record: [`SPEC.md`](SPEC.md); verified free sources: [`SOURCES.md`](SOURCES.md). The repo is `daily-macro-brief`, but on the box the directory, systemd units, database and ports are all still called `daily-feeds`.

## How it works

```
systemd timer 21:10 UTC (= 06:10 JST)
  └─ run.py                 orchestrator + OAuth preflight
      ├─ fetch.py           27 feeds → SQLite, URL dedupe, 48h gate
      ├─ market.py          Yahoo chart API → computed snapshot (7 symbols)
      ├─ triage.py          prefilter.py → Sonnet: cluster, score, thread, translate
      │                     ↳ publishes regime note + thin tail immediately
      ├─ dive.py            top ≤3 above floor, 3-wide parallel Opus sessions
      │                     ↳ each row goes 'researching' before its call, publishes on completion
      └─ speech.py          local Piper TTS → one .m4a per dive + a roll-up
                            ↳ non-fatal: the brief has already published by here
   ↓ writes                                   ↓ writes
~/.openclaw/data/daily-feeds.sqlite      ~/.openclaw/data/daily-feeds-audio/<date>/*.m4a
   ↓ read by
web/  Next.js reader — 127.0.0.1:18793 → tailnet :8446   (the UI itself writes only watchlist + settings)
```

- **Code owns the numbers.** Every market number is computed in Python and handed to the model. The `macro-dive` skill (`.claude/skills/macro-dive/SKILL.md`, appended to each dive's system prompt by `dive.py`) forbids stating any figure that is neither in the bundle nor fetched-and-cited in-session.
- **LLM stages are the local `claude -p` CLI** (no API key). Triage is Sonnet with no tools; dives are Opus with `WebSearch,WebFetch` only, up to 30 min each.
- **Prefilter, then floor.** `prefilter.py` drops template filler by headline *format*, never by topic: ~730 in-window items → 140 (triage retries 140 → 70 → 40 on timeout). Floor is 55; zero dives is a valid outcome.
- **Cross-language clustering.** Sonnet merges ja+en items into one event (the BOJ Review published in both languages became one); no string-similarity method reaches that.
- **Dive contract.** 12 fixed headings, 900–1,600 words with per-section caps; `dive.py audit()` checks sections, frontmatter, verdict values, length and Google-redirect citations, records violations on the dive, and the UI shows them as a footnote.
- **Audio** runs after publish and is non-fatal: a slow or broken render costs audio, never the brief. The roll-up concatenates the PCM already rendered for each dive.
- **Dashboard** (`web/`, pages `/` and `/watchlist`) with reading controls: paper/dark theme and three prose sizes (17/19/21 px), persisted per device in `localStorage` and applied by an inline `<head>` script before first paint (reading it in React state would flash the brightest screen the app can render at 06:40). Fonts are fetched at build time by `next/font` and served from the same origin, so the tailnet-only page needs no public internet to read.
- **Reading surface** (rebuilt 2026-08-05 against four measured problems): dive line length ~92 → ~68–72 characters (`max-width: 64ch` on dive prose only); `faint` text on `surface` 2.75:1 (fails AA) → 4.9:1 (`#736e64`), with `fainter` reserved for decoration; ~14 ad-hoc font sizes → 5 steps (`.t-label` / `.t-meta` / `.t-ui` / `.t-ui-lg` / `--prose-size`). The size control scales prose only: rescaling labels and tables makes the page wobble without making anything easier to read. Serif is Source Serif 4 (higher x-height than the earlier Newsreader).
- **What a dive finds that a digest cannot** (2026-08-04 spike on the US–Japan joint yen intervention: ~25 min, 2,176 words, all 12 sections, verdict `ambiguous`/`medium`, because it declines to force a call): the US sold **euros, not dollars** (~$5–10bn against Japan's ~¥11tn), so the real US deliverable was the **FIMA repo facility**, a credit line rather than ammunition, motivated by avoiding forced UST liquidation into the long end; the BOJ **held the same day, 8–1**, so the price of US help is Japanese rate hikes, which de-rate exactly the long-duration small-cap growth in this book; and rising BOJ odds bid the banks *inside* the Nikkei you are short, eroding the hedge from within.

| Measured | Result |
|---|---|
| First full run (2026-08-04) | fetch 3 s, market 1 s, triage 711 s (140 items → 14 events, 3 above floor, 6 threads), 3 parallel Opus dives 577 s, all `ambiguous`/`medium` → **~21.5 min**; a 21:10 UTC start finishes ~06:32 JST. Ranking was sound: joint intervention (90, risk-off), BOJ hike timeline pulled forward to Sept–Oct (78, risk-off), Bessent asking the Fed for help (75, ambiguous), with the weak `10年債入札` correctly in the tail |
| Audio (2026-08-05, `en_US-ryan-high`, 3 workers) | dives 9.5–11.3 min of audio each (render 339–389 s) + 33.5 min roll-up (88 s, concatenation) → 1,170 s total, ~1.9× realtime, 24 MB |

**Status (2026-08-04):** built and deployed; all stages work (27/27 feeds return items, 7/7 symbols, prefilter 730 → 140, triage degrades 140 → 70 → 40); both timers are enabled and `:8446` is in `tailscale-serve-apps.sh`. The watchlist starts empty and needs your real tickers at `/watchlist`.

**Watchlist picker.** Type `6920`, `レーザー`, `rezateku` or `lasertec` and the listing fills ticker, name, market, sector and a suggested beta bucket. It searches a local mirror of JPX's 東証上場銘柄一覧 (`tickers`, ~4,400 rows): no per-keystroke network call, no third-party symbol API. It degrades to manual entry (unsynced mirror, fresh IPO, foreign line).

- **Refreshed weekly by its own timer**, not as a stage of `run.py`: a network fetch in the 06:10 JST path would be a new way for the morning to fail, and 20:00 UTC clears 21:10 UTC so the two never write the SQLite file at once. `Persistent=true`, so a week missed to a reboot runs on the next boot.
- **Timer and the dashboard's "Sync now" button are one code path.** The unit is templated on its trigger (`daily-feeds-tickers@timer.service` vs `@manual.service`); both run `tickers.py --weekly` and land in `ticker_syncs`, which the **Ticker mirror** panel at the bottom of `/watchlist` lists. A run that starts while another is going records `skipped` and exits 0.
- JPX stamps the file month-end, so most weekly runs legitimately record "no change"; the panel says so.
- **`--names` is the optional half.** JPX ships no English column and kanji cannot be romanised locally, so latin queries reach kanji-named companies (任天堂, 極洋) only once Yahoo's English names are backfilled: ~3,900 throttled requests, ~30 min, resumable, never overwritten by `--sync`. The 3,107 listings with kana in the name are searchable in latin without it via the derived `romaji` column (`レーザーテック` → `rezatekku rezateku`).

## Setup

Needs: Python 3.12 (system `python3` runs every stage except audio and tickers; stdlib only), [`uv`](https://docs.astral.sh/uv/), Node ≥ 22.13 (the reader uses built-in `node:sqlite`; the box runs v24.18), `ffmpeg` (AAC `.m4a` encode/decode), the Claude Code CLI `claude` on `PATH` and logged in, and internet at build time (fonts).

```bash
mkdir -p logs                          # systemd `append:` creates the file, not the directory
uv venv .venv --python 3.12            # `python3 -m venv` is broken on this box (no python3.12-venv)
uv pip install --python .venv/bin/python piper-tts xlrd     # tested with piper-tts 1.6.0, xlrd 2.0.2
.venv/bin/python -m piper.download_voices en_US-ryan-high --data-dir ~/.local/share/piper-voices
(cd web && npm ci && npm run build)    # `next start` needs a build first
```

- The venv serves **audio** (piper) and the **ticker mirror** (xlrd). `run.py` skips audio with a printed note when `.venv` is absent, rather than failing the brief.
- `en_US-ryan-high` is the default: the most natural English Piper voice, ~2× realtime on this box's 4 cores. `en_US-lessac-medium` is ~6× faster and noticeably flatter; switch with `--voice`, or persist it as the `tts_voice` setting.
- No migration step: `scripts/db.py` creates the schema and adds missing columns on first connect. No test suite is checked in; the fixes listed under Gotchas (JST rollover, `recent_closes`, audio glosses) were regression-tested by hand.

## Run / deploy

| | |
|---|---|
| Dashboard | `https://openclaw-vps.tail0d53dc.ts.net:8446/` (loopback `127.0.0.1:18793`) |
| Brief | `daily-feeds.timer` → `daily-feeds.service` (oneshot, `python3 scripts/run.py`, 1 h cap): **21:10 UTC daily = 06:10 JST**; log `logs/run.log` |
| Web | `daily-feeds-web.service` (systemd --user, `Restart=always`): `npm start` = `next start -H 127.0.0.1 -p 18793` in `web/` |
| Ticker mirror | `daily-feeds-tickers.timer` → `daily-feeds-tickers@timer.service`: Mondays 20:00 UTC (+≤10 min jitter); log `logs/tickers.log` |
| Tailnet | `tailscale serve` `:8446` → `127.0.0.1:18793`, re-asserted by `tailscale-serve-apps.timer` within 3 min after gateway restarts (`systemctl --user start tailscale-serve-apps.service` forces it) |

The unit files live in `~/.config/systemd/user/` and are **not** in this repo. The brief timer is fixed in UTC on purpose: JST has no DST but the US does, so the US close lands at 05:00 JST in summer and 06:00 in winter (~45 min of window); UTC keeps the run at a constant 06:10 JST, and parallel dives with incremental publish absorb the rest.

```bash
python3 scripts/run.py                 # full run (what the timer does)
python3 scripts/run.py --skip-dives    # stop after triage; dives are the expensive part
python3 scripts/run.py --skip-audio    # stop after dives
python3 scripts/run.py --force         # re-run a date whose dives finished (re-triaging CASCADE-deletes them)

# stages individually: analysis re-runs on cached articles, no re-fetching
python3 scripts/fetch.py
python3 scripts/market.py
python3 scripts/triage.py --floor 55 --max-deep 3
python3 scripts/dive.py                # or --event <id> for one

# audio (needs the venv: piper is not stdlib)
PYTHONPATH=scripts .venv/bin/python scripts/speech.py             # dives + roll-up
PYTHONPATH=scripts .venv/bin/python scripts/speech.py --dry-run   # print the spoken script only
PYTHONPATH=scripts .venv/bin/python scripts/speech.py --force     # re-render, ignoring cache

# watchlist: seed from a file instead of the UI (one-shot, idempotent; see Data)
python3 scripts/seed_watchlist.py

# TSE ticker mirror (venv: xlrd); the weekly timer and the "Sync now" button both run --weekly
PYTHONPATH=scripts .venv/bin/python scripts/tickers.py --weekly   # sync + fill new listings
PYTHONPATH=scripts .venv/bin/python scripts/tickers.py --sync     # JPX refresh only
PYTHONPATH=scripts .venv/bin/python scripts/tickers.py --runs     # recent sync history
PYTHONPATH=scripts .venv/bin/python scripts/tickers.py --stats    # coverage by market
PYTHONPATH=scripts .venv/bin/python scripts/tickers.py --search レーザー
PYTHONPATH=scripts .venv/bin/python scripts/tickers.py --names    # English names, ~30 min, optional
systemctl --user list-timers daily-feeds-tickers.timer
systemctl --user start daily-feeds-tickers@manual.service         # what the button does
journalctl --user -u 'daily-feeds-tickers@*' -n 50

# debugging
python3 scripts/prefilter.py --show-kept --show-dropped           # audit the prefilter against today's feed
python3 scripts/triage.py --dry-run | less                        # the exact prompt triage will send
python3 scripts/bundle.py "日米 協調介入 円" --query-en "Japan US joint yen intervention"   # one dive bundle

cd web && npm run deploy               # next build + restart service + health check
```

## Configuration

No `.env` file is used, so there is no `.env.example`. Everything is an environment variable with a default, or a row in the database `settings` table.

| Variable | Read by | Meaning |
|---|---|---|
| `DAILY_FEEDS_DB` | scripts, web | SQLite path (default `~/.openclaw/data/daily-feeds.sqlite`) |
| `DAILY_FEEDS_AUDIO` | scripts, web | audio directory (default `~/.openclaw/data/daily-feeds-audio`) |
| `PIPER_VOICES` | `speech.py` | Piper voice directory (default `~/.local/share/piper-voices`) |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | `speech.py --engine gemini` only | Gemini TTS key; if unset it is read from `~/.openclaw/openclaw.json` (`models.providers.google.apiKey`), outside the repo. Nothing in-tree holds a key |
| `NODE_ENV=production` | web unit | set by `daily-feeds-web.service` |

- **Claude auth** is the box's `claude` CLI login (OAuth), not a key. `run.py` proves the CLI can complete a turn before committing to a run.
- **`settings` table** (edited in the UI): `book_style`, `sectors_of_interest`, `tts_engine`, `tts_voice`. Code defaults: relevance floor 55 (`--floor`), `--max-deep 3`, prefilter budget 140, dive `--timeout 2100 --jobs 3`, models `sonnet` (triage) / `opus` (dives).
- **Watchlist seed:** `config/watchlist.example.json` is a schema reference with placeholder tickers. To start from a file, copy it to `config/watchlist.json` (gitignored: it holds positions), fill it in, run `seed_watchlist.py`. With an empty watchlist the dives speak in sectors and Growth250 beta rather than inventing names.

## Data

| What | Where | In git |
|---|---|---|
| Brief database (WAL) | `~/.openclaw/data/daily-feeds.sqlite` | no |
| Audio | `~/.openclaw/data/daily-feeds-audio/<date>/*.m4a` | no |
| Piper voices | `~/.local/share/piper-voices/` | no |
| Logs | `logs/run.log`, `logs/tickers.log` | no (ignored) |
| `.venv/`, `web/node_modules/`, `web/.next/` | rebuilt by Setup | no |
| Real watchlist | `config/watchlist.json` (optional seed) and the `watchlist` table | no (private) |
| Placeholder watchlist, dive skill, specs, sources | `config/watchlist.example.json`, `.claude/skills/macro-dive/SKILL.md`, `SPEC.md`, `SOURCES.md` | yes |

- **Tables** (canonical: `scripts/db.py`, described in `SPEC.md` §7): `briefs`, `feeds`, `items`, `threads`, `events`, `event_items`, `dives`, `market_snapshots`, `watchlist`, `tickers`, `ticker_syncs`, `audio`, `settings`. The pipeline owns all brief data; the UI writes only `watchlist` and `settings`. WAL is required: the Next.js reader holds a handle open while Python writes.
- **Rebuild:** an empty database fills itself: `run.py` builds today's brief, `tickers.py --weekly` rebuilds the JPX mirror, `speech.py --force` re-renders audio. **Not rebuildable:** past dives (10–25 min of Opus each; `dives` keeps verdict + inputs as an auditable track record over months) and the watchlist/settings; back up the SQLite file.

## Related

- Same shape as `ledger-web`, `human-graph` and `myself`: SQLite + loopback Next.js UI behind Tailscale. Listed on the `/apps` hub page.
- `granger` (causal journal) reads `daily-feeds.sqlite` read-only (per the box's `CLAUDE.md`).
- Shares the box's one Claude OAuth credential and rate-limit pool with every other Claude agent (`ledger`, `people`, `myself`, `granger`, `news-synthesizer`).

## Gotchas

- ⚠ **Gemini quota is per-day, not per-minute.** `gemini-2.5-flash-preview-tts` allows **10 requests/day** on the free tier (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`); one brief needs ~40 calls. That is why TTS is local **Piper** and `--engine gemini` stays wired but unused: enough to prove it works, nowhere near enough to run it. A 429 means the day's allowance is gone; backing off does not help. Gemini also returns nothing for inputs of 2,000+ characters (`finishReason=OTHER`, zero output, no error), hence `GEMINI_CHUNK = 1100` with halve-and-retry.
- **Do not register these feeds in `blogwatcher`.** It has no namespacing (one global feed list and read/unread state), so `read-all` here would silently destroy the `news-synthesizer` pipeline's state. That collision is why this repo is standalone.
- **The claude-cli OAuth token is ~8 h.** The 21:10 UTC run lands after a daytime token expires, so it depends on unattended refresh rotation. A preflight failure writes `briefs.error`, which the dashboard renders in red: a silent no-brief morning is the worst outcome because it looks like a quiet market.
- **Latency is not a function of prompt size.** One shared credential and rate-limit pool means an identical `claude -p` call has ranged from ~2 to ~20 min depending on what else is running. Don't tune timeouts as if it were.
- **Google News item URLs cannot be resolved programmatically** (the ID decodes to a server-side token; real resolution needs a signed `batchexecute` POST). They stay clickable in the UI, but the dive skill requires citing the publisher's own URL.
- **`--allowedTools` does not sandbox file reads.** The spike cited `SPEC.md:139` despite being given only `WebSearch,WebFetch`. Don't rely on it for isolation.
- **`next start` needs `next build` first.** `npm run deploy` does both, but its health check hits `/api/brief`, which 404s on an empty database, so it reports failure until the first brief exists.
- **Gateway restarts wipe `tailscale serve` mappings** (`resetOnExit`); the timer in *Run / deploy* restores `:8446` within 3 minutes.
- **A citation proves provenance, not accuracy.** Two dives once disagreed on the same Nikkei close (63,445.53 / −1.4% vs 63,754.90 / −0.94%); the feed itself settled it, so the first was wrong *despite carrying a citation*. Fixed structurally: `market.py` hands every instrument `recent_closes` (the last five dated sessions with percent change), so a dive never needs to look up a recent close.
- **A false quiet day is the worst failure mode.** `dive.py --event` once took its brief from the *clock*, so a run past midnight JST published an empty brief for tomorrow that the UI rendered as "nothing cleared the relevance floor". Fixed at the root (`--event` takes its brief from the event; a single-event run never publishes a brief) and guarded in the UI (it prefers the newest brief with a market snapshot). `status='published'` with zero market rows is the signature of a fake one.
- **Audio was verified by transcribing it back**, the only way to catch a synthesiser saying the wrong thing. It found `202円高` ("up 202 yen") glossed as the standalone term 円高 ("yen strength"), inverting a Nikkei move, and 「…」 quoted headlines read word-by-word into noise. Fixed: quoted Japanese spans are dropped whole and 円高/円安 carry a preceding-digit guard. Piper is monolingual, so remaining Japanese is glossed or dropped (personal names are lost); `Nikkei` → "Nik" and `TOPIX` → "topics" are known and unfixed.
- **Dive length** overran (2,176 / 2,006 / 2,126 / 2,303 words vs 900–1,600) until per-section caps and the `audit()` check; a validation dive then came in at 1,321 words, audit clean, 11 sources, and denser rather than thinner (it contradicted its own triage score, using two snapshot figures exactly and labelling a level it derived `(derived)`): length was never depth. Spike dives were checked for sourcing: 13/15 cited non-Google URLs returned 200 (the failures were Bloomberg bot-blocks) and all 8 quoted Japanese strings matched the MOF primary source verbatim. In the first full run 48/51 cited URLs resolved (the 3 failures were Bloomberg 403 bot-blocks, not fabrications) and there were **zero invented market numbers**: every figure was a snapshot value used exactly or fetched with a citation, and paywalled sources were marked `[paywalled]`.

**Known gaps (accepted, `SPEC.md` §1):** Nikkei scoops (観測記事) cannot be replaced by a free pipeline; consensus-vs-actual for economic releases has no free source; `^NKVI` is unavailable (JP vol is proxied by realized vol on Growth250 + `^VIX`); Kalshi lists a well-shaped BOJ market but serves **no prices** without an API key (the highest-value v2 upgrade; Polymarket serves prices but covers macro thinly); JP official statistics (MOF / Cabinet Office / METI / Stat Bureau) expose no working RSS.

## License

MIT. See [LICENSE](LICENSE).
