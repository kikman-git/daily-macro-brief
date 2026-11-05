# Free source inventory — every entry HTTP-tested 2026-08-04

Method: `curl -sSL` with a browser UA, counting `<item>`/`<entry>` elements. Only feeds that
returned 200 **with parsable items** are listed as usable.

## A. Japanese — primary / official (highest trust, t=0 latency)

| Source | Feed | Items | Why it matters |
|---|---|---|---|
| **BOJ 日本語** | `https://www.boj.or.jp/rss/whatsnew.xml` | 57 | The statement itself, unmediated. Beats Nikkei, which is a rewrite at t+30min. |
| BOJ English | `https://www.boj.or.jp/en/rss/whatsnew.xml` | ok | Same, EN |
| FSA 日本語 | `https://www.fsa.go.jp/fsaNewsListAll_rss2.xml` | ok | Regulation, enforcement |
| FSA English | `https://www.fsa.go.jp/fsaEnNewsList_rss2.xml` | ok | Same, EN |
| JPX news | `https://www.jpx.co.jp/rss/jpx-news.xml` | 11 | Exchange notices, rule changes |

## B. Japanese — news & analysis

| Source | Feed | Items | Notes |
|---|---|---|---|
| **NHK 経済** | `https://www3.nhk.or.jp/rss/news/cat5.xml` | 80 | Fastest domestic econ/policy wire that's free |
| 東洋経済オンライン | `https://toyokeizai.net/list/feed/rss` | 20 | Analysis / deep-dive — closest free analogue to Nikkei's interpretive pieces |
| ダイヤモンド | `https://diamond.jp/list/feed/rss/dol` | 25 | Analysis |
| Yahoo!ニュース 経済 | `https://news.yahoo.co.jp/rss/topics/business.xml` | 8 | Aggregated top econ — good breadth signal |
| ZUU online | `https://zuuonline.com/feed` | 30 | Retail-investor finance |
| jiji ranking | `https://www.jiji.com/rss/ranking.rdf` | 10 | Wire, ranking-only (no topical econ feed found) |
| Investing.com JP econ | `https://jp.investing.com/rss/news_14.rss` | 10 | Closest free thing to an econ calendar |
| Investing.com JP market | `https://jp.investing.com/rss/market_overview.rss` | 10 | Market overview |

## C. Google News RSS — the universal adapter (KEY FINDING)

Turns any query, and critically any **site**, into a feed. Free, ~100 items, JP locale.
This is how sources with no RSS get reached.

```
https://news.google.com/rss/search?q=<QUERY>+when:2d&hl=ja&gl=JP&ceid=JP:ja
```

| Query | Items | Solves |
|---|---|---|
| `site:kabutan.jp` | **100** | **kabutan publishes no RSS at all.** Returns 決算速報, レーティング日報, 話題株ピックアップ, 明日の決算発表予定 — the single-stock/sector layer. |
| `site:jp.reuters.com` | **100** | **Reuters direct feed 404s.** Returns full Reuters Japan incl. コラム analysis pieces. |
| `日銀 金利` | 49 | BOJ keyword net |
| JP business topic feed | 70 | Broad domestic econ |

Gotchas: `when:1d` returned 0 items on some queries — use `when:2d` and apply the date gate
downstream.

**Item URLs cannot be resolved programmatically.** Investigated 2026-08-04: following the
redirect returns a JS Angular shell (HTTP 200, no `Location`), and base64-decoding the
`CBMi…` article ID yields an opaque server-side token (`AU_yqLM…`), not a URL. Real resolution
needs a signed POST to `/_/DotsSplashUi/data/batchexecute`. **Not worth building.** Mitigation:
the bundle carries `title` + `source` per item, and the dive model is instructed to find the
publisher's own URL during research — which works in practice (the 2026-08-04 spike cited
direct `mof.go.jp`, `nikkei.com`, `cnbc.com` links unprompted). Google links must never reach
the rendered brief.

## D. US / global — primary (free, authoritative, better than Nikkei's US desk)

| Source | Feed | Items |
|---|---|---|
| Fed monetary press | `https://www.federalreserve.gov/feeds/press_monetary.xml` | 15 |
| Fed speeches | `https://www.federalreserve.gov/feeds/speeches.xml` | 15 |
| BEA | `https://apps.bea.gov/rss/rss.xml` | 47 |
| ECB press | `https://www.ecb.europa.eu/rss/press.html` | 15 |
| CNBC top | `https://www.cnbc.com/id/100003114/device/rss/rss.html` | 30 |
| MarketWatch top | `https://feeds.marketwatch.com/marketwatch/topstories/` | 10 |
| Yahoo Finance | `https://finance.yahoo.com/news/rssindex` | 41 |
| Investing.com US econ | `https://www.investing.com/rss/news_14.rss` | 10 |
| Financial Times | `https://www.ft.com/rss/home` | 10 |
| **US macro (Google News EN)** | `…/rss/search?q=Federal+Reserve+OR+inflation+OR+"interest+rates"…&hl=en-US&gl=US&ceid=US:en` | **100** |

The English keyword net is the US-side counterpart to the JP adapters, and it is what makes the
US tape reachable in depth — the Fed/ECB primary feeds are *event* feeds that legitimately
return zero items on a normal day (the 48h gate correctly drops a FOMC statement from 6 days
ago), so without it a quiet-Fed week would leave the US side nearly empty.

⚠ **`WSJ markets` (`feeds.a.dj.com/rss/RSSMarketsMain.xml`) was removed.** It returns 20 items
and HTTP 200, but every one is dated **January 2025** — the feed is abandoned upstream. It looks
healthy by item count, which is exactly why item counts alone are not a health check; the 48h
gate silently discarded 100% of it. Recency, not item count, is the test.

⚠ **`MarketWatch` needed a parser fix.** It emits `<guid>WP-MKTW-0005160879</guid>` *before*
`<link>`, so a URL extractor that scans children in document order stores an opaque internal id
as the article URL for every item. `fetch.py`'s `text()` helper honours argument order for this
reason. 13 such rows were ingested and purged before the first real brief.

## E. Market data — free, no API key

Yahoo chart endpoint: `https://query1.finance.yahoo.com/v8/finance/chart/<SYM>?range=1mo&interval=1d`

| Symbol | Instrument | Verified |
|---|---|---|
| `^N225` | Nikkei 225 | ✓ |
| `1305.T` | TOPIX ETF | ✓ |
| **`2516.T`** | **東証グロース250 ETF — high-beta small-cap proxy** | ✓ |
| `JPY=X` | USD/JPY | ✓ |
| `^VIX` | VIX | ✓ 15.69 |
| `^SOX` | PHLX Semiconductor — dominant driver of JP high-beta | ✓ 11430 |
| `^GSPC` | S&P 500 | ✓ 7600.5 |

**`^NKVI` (Nikkei VI) → Not Found.** Proxy JP vol with realized vol on `2516.T` + `^VIX`.

## F. Prediction markets — investigated in detail 2026-08-04

Endpoints all return 200 unauthenticated, but **price availability is the real constraint**:

| API | Endpoint | Prices without auth? |
|---|---|---|
| Polymarket Gamma | `https://gamma-api.polymarket.com/markets?limit=N&closed=false` | **Yes** — `outcomePrices` populated |
| Polymarket CLOB | `https://clob.polymarket.com/markets` | Yes |
| Kalshi | `https://api.elections.kalshi.com/trade-api/v2/...` | **No** — see below |

### Polymarket: prices work, macro coverage is thin
Scanned 400 open markets. Only macro hits were `Fed abolished before 2027?` and
`Will Donald Trump visit Japan in 2026?` — plus one genuinely usable contract:
`Will the Fed decrease interest rates by 50+ bps after the October 2026 meeting?`
→ **Yes 0.015 / No 0.985**. So: a usable but narrow Fed signal.

### Kalshi: rich catalog, no accessible prices
Catalog is far better — 617 Economics + 742 Financials series. Relevant live series exist:
- **`KXCBDECISIONJAPAN`** — "Bank Of Japan policy interest rate decision", live events
  (`-26SEP17`, `-26JUL30`, `-26JUN15`…), outcomes exactly right:
  maintain / hike 25bp / cut 25bp / hike >25bp / cut >25bp
- **`KXFED`** — Fed funds rate after each meeting (`KXFED-26SEP`, `-26OCT`, …)
- Also `KXJPCPIYOY` (Japan inflation YoY), `KXJOBLESSCLAIMS`, `GDP`, `KXUST2AD`
- Note the **`KX` prefix** — bare `FED` / `FEDDECISION` / `KXBOJDECISION` are dormant legacy
  series (`KXBOJDECISION` has one event, from March 2025). Don't query those.

**But: `0/1000` open markets expose `last_price`, `yes_bid`, or `volume` unauthenticated**, and
`KXCBDECISIONJAPAN-26SEP17`'s orderbook is genuinely empty (`yes_dollars: []`, zero trades).
So Kalshi currently yields structure without signal. Hosts: use `api.elections.kalshi.com`;
`trading-api.kalshi.com` returns 401 + a migration notice and `api.kalshi.com` does not resolve.

### Consequence for the brief
Report the Polymarket Fed contract where relevant. For the **BOJ, do not claim a market price** —
use JGB/OIS moves plus analyst consensus, explicitly labelled as a proxy.
**v2:** a free Kalshi API key would unlock real Fed *and* BOJ probabilities and is the single
highest-value upgrade to the odds section.

## G. Failed — do not retry without a new approach

| Source | Result |
|---|---|
| kabutan direct RSS (`/rss/news.rdf`, page scrape) | 404 / no RSS in HTML → use Google News `site:` |
| Reuters JP direct (`jp.reuters.com/arc/outboundfeeds/...`) | 404 → use Google News `site:` |
| Nikkei direct RSS | 404 (paid) |
| **WSJ markets** (`feeds.a.dj.com/rss/RSSMarketsMain.xml`) | 200 with 20 items, all **Jan 2025** — abandoned upstream. Removed 2026-08-04. |
| MINKABU, Traders Web, Bloomberg JP | 404 |
| jiji topical econ feed | 404 (only ranking works) |
| **MOF** (`/rss/new_release.xml`, `/rss/topics.xml`) | 404 |
| **METI** | 403 |
| **統計局 / 内閣府 ESRI** | 404 |
| US Treasury press | 404 |
| BLS `news_release.rss` | 403 on default UA |

**Gap:** JP official statistics (MOF / Cabinet Office QE / METI / Stat Bureau) expose no
working RSS. Options if this becomes binding: e-Stat API (free, needs appId), or scheduled
scrapes of their release calendars.

`assets.wor.jp/rss/rdf/nikkei/markets.rdf` returned 30 items and appears to be a third-party
Nikkei headline mirror. **Not adopted** — verify legitimacy/ToS before relying on it.
