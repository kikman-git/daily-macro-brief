#!/usr/bin/env python3
"""Stage 2 — the computed market snapshot.

Every market number in the brief originates here, in code. The model is never asked to
recall a price (SPEC decision 5): it may reason freely about what -3.1% on Growth250 means,
but it must not be able to invent that number.

Usage: market.py [--date YYYY-MM-DD]
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime

import db as dbm

JST = dbm.JST

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

SYMBOLS = {
    "^N225":  "Nikkei 225",
    "1305.T": "TOPIX ETF",
    "2516.T": "Growth250 ETF (high-beta proxy)",
    "JPY=X":  "USD/JPY",
    "^VIX":   "VIX",
    "^SOX":   "PHLX Semiconductor",
    "^GSPC":  "S&P 500",
}

DERIVED = ("vs_ma20_pct", "vs_ma50_pct", "drawdown_from_60d_high_pct",
           "realized_vol_20d_annualized_pct", "recent_closes")


def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def pct(a, b):
    return None if not b else round((a / b - 1) * 100, 2)


def snapshot():
    """Daily bars -> last, overnight change, MA20/50 distance, drawdown, realized vol.

    ^NKVI (Nikkei VI) is not available on the free endpoint, so Japanese vol is proxied by
    realized vol on Growth250 plus ^VIX.
    """
    out = {}
    for sym, label in SYMBOLS.items():
        try:
            u = ("https://query1.finance.yahoo.com/v8/finance/chart/"
                 f"{urllib.parse.quote(sym)}?range=6mo&interval=1d")
            d = json.loads(get(u))["chart"]["result"][0]
            pairs = [(t, c) for t, c in zip(d.get("timestamp") or [],
                                            d["indicators"]["quote"][0]["close"])
                     if c is not None]
            closes = [c for _, c in pairs]
            if len(closes) < 25:
                out[sym] = {"label": label, "error": "insufficient history"}
                continue
            last, prev = closes[-1], closes[-2]
            ma20 = sum(closes[-20:]) / 20
            ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
            hi60 = max(closes[-60:]) if len(closes) >= 60 else max(closes)
            rets = [closes[i] / closes[i - 1] - 1 for i in range(-20, 0)]
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            out[sym] = {
                "label": label,
                "last": round(last, 2),
                "chg_pct_1d": pct(last, prev),
                "vs_ma20_pct": pct(last, ma20),
                "vs_ma50_pct": pct(last, ma50) if ma50 else None,
                "drawdown_from_60d_high_pct": pct(last, hi60),
                "realized_vol_20d_annualized_pct": round(var ** 0.5 * (252 ** 0.5) * 100, 1),
                # The last five sessions, dated. Added because two dives analysing overlapping
                # events disagreed on the same prior close -- one cited an aggregator that had
                # it wrong (63,445.53 / -1.4% vs the correct 63,754.90 / -0.94%). A number the
                # model keeps needing and keeps getting wrong should be computed, not fetched.
                "recent_closes": [
                    {"date": datetime.fromtimestamp(t, JST).date().isoformat(),
                     "close": round(c, 2),
                     "chg_pct": pct(c, pairs[i - 1][1]) if i else None}
                    for i, (t, c) in list(enumerate(pairs))[-5:]
                ],
                "asof": d["meta"].get("regularMarketTime"),
            }
        except Exception as e:
            out[sym] = {"label": label, "error": f"{type(e).__name__}: {e}"}
    return out


def persist(db, brief_id, snap):
    for sym, s in snap.items():
        db.execute(
            "INSERT INTO market_snapshots(brief_id,symbol,label,last,chg_pct,extras_json,asof) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(brief_id,symbol) DO UPDATE SET "
            "last=excluded.last, chg_pct=excluded.chg_pct, extras_json=excluded.extras_json, "
            "asof=excluded.asof",
            (brief_id, sym, s.get("label"), s.get("last"), s.get("chg_pct_1d"),
             json.dumps({k: s[k] for k in DERIVED + ("error",) if k in s}, ensure_ascii=False),
             str(s.get("asof") or "")))
    db.commit()


def load(db, brief_id):
    """Read the persisted snapshot back in bundle shape, so dives reuse the stored numbers."""
    out = {}
    for r in db.execute("SELECT * FROM market_snapshots WHERE brief_id=?", (brief_id,)):
        try:
            extras = json.loads(r["extras_json"] or "{}")
        except Exception:
            extras = {}
        out[r["symbol"]] = {"label": r["label"], "last": r["last"],
                            "chg_pct_1d": r["chg_pct"], "asof": r["asof"], **extras}
    return out


def main():
    date_jst = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else None
    db = dbm.connect()
    brief_id = dbm.get_or_create_brief(db, date_jst)
    snap = snapshot()
    persist(db, brief_id, snap)
    ok = sum(1 for s in snap.values() if "error" not in s)
    print(f"brief={brief_id} symbols ok={ok}/{len(snap)}")
    for sym, s in snap.items():
        if "error" in s:
            print(f"  FAIL {sym}: {s['error']}", file=sys.stderr)
        else:
            print(f"  {sym:8} {s['last']:>10}  {s['chg_pct_1d']:+.2f}%  "
                  f"ma20 {s['vs_ma20_pct']:+.2f}%  rv20 {s['realized_vol_20d_annualized_pct']}%")
    db.close()


if __name__ == "__main__":
    main()
