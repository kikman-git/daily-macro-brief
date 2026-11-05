#!/usr/bin/env python3
"""The feed registry. Every entry here was HTTP-tested — see SOURCES.md for counts and for
the list of sources that failed and why.

Do NOT register any of these in `blogwatcher`. It has no namespacing (one global feed list,
one global read/unread state), so `read-all` here would silently destroy the
news-synthesizer pipeline's state. That collision is why this repo is standalone.
"""
import urllib.parse

# Google News RSS is a universal adapter: it turns any query -- and critically any *site* --
# into a feed, which is how kabutan (publishes no RSS) and Reuters Japan (direct feed 404s)
# get reached. Item URLs are opaque redirect tokens that cannot be resolved programmatically;
# the dive model is instructed to find the publisher's own URL during research.
GNEWS = "https://news.google.com/rss/search?q={q}+when:2d&hl={loc}"
_LOC = {"ja": "ja&gl=JP&ceid=JP:ja", "en": "en-US&gl=US&ceid=US:en"}


def gnews(query, lang="ja"):
    return GNEWS.format(q=urllib.parse.quote(query), loc=_LOC[lang])


# (name, url, kind, lang)
FEEDS = [
    # --- A. Japanese primary / official: the statement itself, unmediated ---
    ("日本銀行 (BOJ)",            "https://www.boj.or.jp/rss/whatsnew.xml",              "jp-official", "ja"),
    ("Bank of Japan (EN)",       "https://www.boj.or.jp/en/rss/whatsnew.xml",           "jp-official", "en"),
    ("金融庁 (FSA)",              "https://www.fsa.go.jp/fsaNewsListAll_rss2.xml",       "jp-official", "ja"),
    ("FSA (EN)",                 "https://www.fsa.go.jp/fsaEnNewsList_rss2.xml",        "jp-official", "en"),
    ("日本取引所 (JPX)",           "https://www.jpx.co.jp/rss/jpx-news.xml",              "jp-official", "ja"),

    # --- B. Japanese news & analysis ---
    ("NHK 経済",                  "https://www3.nhk.or.jp/rss/news/cat5.xml",            "jp-news",     "ja"),
    ("東洋経済オンライン",          "https://toyokeizai.net/list/feed/rss",                "jp-analysis", "ja"),
    ("ダイヤモンド・オンライン",     "https://diamond.jp/list/feed/rss/dol",                "jp-analysis", "ja"),
    ("Yahoo!ニュース 経済",        "https://news.yahoo.co.jp/rss/topics/business.xml",    "jp-news",     "ja"),
    ("ZUU online",               "https://zuuonline.com/feed",                          "jp-news",     "ja"),
    ("時事通信 ランキング",         "https://www.jiji.com/rss/ranking.rdf",                "jp-news",     "ja"),
    ("Investing.com JP 経済",     "https://jp.investing.com/rss/news_14.rss",            "jp-news",     "ja"),
    ("Investing.com JP 市場",     "https://jp.investing.com/rss/market_overview.rss",    "jp-news",     "ja"),

    # --- C. Google News adapters: reach sources that publish no usable RSS ---
    ("kabutan (via Google News)", gnews("site:kabutan.jp"),                             "jp-adapter",  "ja"),
    ("Reuters JP (via Google News)", gnews("site:jp.reuters.com"),                       "jp-adapter",  "ja"),
    ("日銀・金利 (Google News)",    gnews("日銀 金利"),                                    "jp-adapter",  "ja"),
    ("日本株・市場 (Google News)",  gnews("日経平均 株式市場"),                             "jp-adapter",  "ja"),

    # --- D. US / global primary: better than Nikkei's US desk, and free ---
    ("Fed monetary press",       "https://www.federalreserve.gov/feeds/press_monetary.xml", "us-official", "en"),
    ("Fed speeches",            "https://www.federalreserve.gov/feeds/speeches.xml",    "us-official", "en"),
    ("BEA releases",            "https://apps.bea.gov/rss/rss.xml",                     "us-official", "en"),
    ("ECB press",               "https://www.ecb.europa.eu/rss/press.html",             "us-official", "en"),
    ("CNBC top news",          "https://www.cnbc.com/id/100003114/device/rss/rss.html", "us-news",     "en"),
    ("MarketWatch top",        "https://feeds.marketwatch.com/marketwatch/topstories/", "us-news",     "en"),
    ("Yahoo Finance",          "https://finance.yahoo.com/news/rssindex",               "us-news",     "en"),
    ("Investing.com US econ",  "https://www.investing.com/rss/news_14.rss",             "us-news",     "en"),
    ("Financial Times",        "https://www.ft.com/rss/home",                           "us-news",     "en"),
    # The US tape sets the Tokyo open, so the US side gets a keyword net of its own. This
    # replaces the WSJ markets feed, which is abandoned upstream (frozen at Jan 2025).
    ("US macro (Google News)",  gnews("Federal Reserve OR inflation OR \"interest rates\"", "en"),
                                                                                        "us-adapter",  "en"),
]


def sync(db, now):
    """Make the feeds table match this registry: upsert what's here, disable what isn't.

    Disabling rather than deleting keeps historical items joinable to the feed they came from.
    """
    urls = [f[1] for f in FEEDS]
    for name, url, kind, lang in FEEDS:
        db.execute(
            "INSERT INTO feeds(name,url,kind,lang,enabled) VALUES(?,?,?,?,1) "
            "ON CONFLICT(url) DO UPDATE SET name=excluded.name, kind=excluded.kind, "
            "lang=excluded.lang, enabled=1",
            (name, url, kind, lang))
    db.execute(f"UPDATE feeds SET enabled=0, last_status='retired from registry' "
               f"WHERE url NOT IN ({','.join('?' * len(urls))})", urls)
    db.commit()
    return db.execute("SELECT * FROM feeds WHERE enabled=1 ORDER BY kind, name").fetchall()
