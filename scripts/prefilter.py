#!/usr/bin/env python3
"""Deterministic noise removal and payload budgeting, ahead of semantic triage.

Why this exists: a full day is ~730 in-window items, and handing 260 of them to Sonnet took
over 15 minutes — which would blow the ~45-minute winter pre-open window on its own. But the
volume is not *information*: the adapter feeds are dominated by template-shaped filler
(決算速報 earnings flashes, レーティング日報, sector ranking tables, Reuters ticker quote stubs) and
the official feeds carry a steady drip of administrative publications (stewardship-code lists,
research papers, financial-education events).

The division of labour is the same as everywhere else in this pipeline: **code does the
mechanical work, the model does the semantic work.** Dropping `デクセリ、4-6月期(1Q)最終は12％増益で着地`
needs a regex, not a language model. Deciding that `日米協調介入` and "joint intervention" are the
same event needs a language model, not a regex.

Two mechanisms, in order:
  1. Drop template-shaped filler by headline *format* (never by topic).
  2. Score what survives and keep the top BUDGET items, so prompt size — and therefore triage
     wall-clock — is bounded no matter how loud the news day is.

Nothing here decides that an event is *unimportant*. That judgement belongs to triage, which
owns the relevance floor. This stage only decides what is worth a model's attention at all.

Audit the rules against today's feed:
    python3 prefilter.py --show-dropped --show-kept
"""
import re
import sys
from collections import Counter

BUDGET = 140          # items handed to triage; ~40KB of prompt, ~4 min of Sonnet
PER_SOURCE_CAP = 12   # no single publisher may eat the budget

# Template-shaped filler. Each pattern matches a headline *format*, not a subject.
NOISE = [
    (r"\d+-\d+月期\(\d+Q\)", "quarterly earnings flash"),
    (r"で着地(?:$|\s)", "earnings landing flash"),
    (r"今期(?:経常|最終|営業)は.{0,12}[増減]益", "guidance flash"),
    (r"(?:上期|通期|今期).{0,10}を\d+[％%].{0,4}(?:上方|下方)修正", "guidance revision flash"),
    (r"騰落ランキング|値上がり率ランキング|値下がり率ランキング", "ranking table"),
    (r"レーティング(?:日報|速報)|目標株価.{0,6}引き(?:上|下)げ", "analyst rating daily"),
    (r"株主優待|新規上場|IPO日程", "retail housekeeping"),
    (r"Stock Price & Latest News", "ticker quote stub"),
    (r"^[A-Z0-9]{1,6}\.[A-Z]{1,3}\s*-", "ticker quote stub"),
    (r"【[↑↓→]】", "index open/close flash"),   # superseded by the computed snapshot
    (r"(?:前場|後場|大引け|寄り付き)(?:終了|概況)?[｜|=＝]", "session tick recap"),
    (r"日経平均、[\d,]+円[\d]*銭?(?:高|安)", "index tick recap"),
    (r"^(?:本日|明日|来週)の(?:予定|スケジュール)", "calendar stub"),
    (r"^PR[:：]|\[PR\]", "sponsored"),
    # Official-feed housekeeping. These publish daily and are never a risk-on/off catalyst.
    (r"（論文）|\(Research Paper\)|IMES DPS", "research paper"),
    (r"スチュワードシップ|コーポレートガバナンス・コード.{0,8}リスト", "code acceptance list"),
    (r"Weekly Review|週刊金融財政|広報(?:誌|活動)", "newsletter"),
    (r"金融経済教育|イベント.{0,6}開催について|セミナー.{0,6}開催", "outreach event"),
    # No rule for JGB auction publications: `入札` is in KEEP, so any such rule would be dead
    # code — and correctly so. `10年債入札「不調」、応札倍率が1年ぶり低さ` is precisely the kind of
    # yield signal this brief exists to catch, and an auction tail is a real BOJ-path input.
]
_NOISE = [(re.compile(p), why) for p, why in NOISE]

# Macro vocabulary. Presence overrides every noise rule: a rule matching the *shape* of a
# headline can still catch a genuinely macro one, and a false drop is worse than a false keep.
KEEP = re.compile(
    r"日銀|日本銀行|BOJ|FOMC|FRB|Fed\b|Federal Reserve|ECB|"
    r"金融政策|政策金利|利上げ|利下げ|マイナス金利|量的|YCC|金融緩和|金融引き締め|"
    r"為替介入|協調介入|円安|円高|ドル円|USD/?JPY|"
    r"物価|インフレ|CPI|GDP|雇用統計|失業率|賃金|春闘|"
    r"国債|入札|長期金利|イールド|JGB|Treasury|"
    r"関税|輸出規制|制裁|tariff|export control|"
    r"景気|リセッション|recession|inflation|interest rate|rate (?:cut|hike|decision)|"
    r"半導体市況|SOX|需給|信用取引|追証|日経平均先物",
    re.I)

OFFICIAL = {"jp-official", "us-official"}
ANALYSIS = {"jp-analysis"}

# Both sides get guaranteed representation. The US tape sets the Tokyo open, so a loud domestic
# news day must not squeeze it out entirely — which is exactly what an unquota'd budget did.
REGION_QUOTA = {"jp": 85, "us": 55}

# Publishers whose macro copy is worth reading, rather than the affiliates and content farms
# that restate it. A bonus, not a whitelist: an unknown publisher is still eligible, it just
# loses ties to Reuters.
PREFERRED = re.compile(
    r"reuters|bloomberg|日本経済新聞|nikkei|nhk|時事|共同|株探|kabutan|東洋経済|ダイヤモンド|"
    r"みんかぶ|axios|cnbc|financial times|\bft\b|wall street journal|wsj|marketwatch|"
    r"yahoo.?finance|japan times|投資と経済|外為どっとコム|trading ?view|barron|economist",
    re.I)


# Google News is full of syndicated wire copy: one Reuters story on the Fed reappeared under
# nine local TV affiliates, identical but for the " - WPDE" / " - KTUL" suffix. The publisher
# suffix and any trailing parenthetical must come off *before* truncation, or every copy
# normalizes to a different key and the whole cluster survives dedup.
_SUFFIX = re.compile(r"\s+[-–—]\s+[^-–—]{1,40}$|\s*[｜|]\s*[^｜|]{1,30}$")
_TRAILING_PAREN = re.compile(r"[（(][^（()）]{0,40}[)）]\s*$")


def _norm(title):
    """Collapse a headline for duplicate detection across feeds carrying the same wire."""
    t = (title or "").strip()
    for _ in range(2):                      # "... - Reuters (2026年8月3日掲載) - ライブドア"
        t = _TRAILING_PAREN.sub("", t).strip()
        t = _SUFFIX.sub("", t).strip()
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[-–—|｜=＝【】\[\]()（）「」『』:：,，、.。\"'“”]", "", t)
    return re.sub(r"\d+", "#", t).lower()[:56]


def region(item):
    return "us" if (item.get("kind") or "").startswith("us") else "jp"


def score(item):
    """Attention priority. A BOJ statement on rates outranks a BOJ paper on quantum optics."""
    title = item.get("title") or ""
    kind = item.get("kind") or ""
    macro = bool(KEEP.search(title))
    if macro and kind in OFFICIAL:
        base = 100
    elif macro and kind in ANALYSIS:
        base = 85
    elif macro:
        base = 75
    elif kind in ANALYSIS:
        base = 45
    elif kind in OFFICIAL:
        base = 25          # routine administrative publication
    else:
        base = 30          # plain news with sector read-through potential
    if PREFERRED.search(item.get("source") or ""):
        base += 12
    return base


def classify(item):
    """-> (keep: bool, reason: str). Noise rules only; budgeting happens in apply()."""
    title = item.get("title") or ""
    if KEEP.search(title):
        return True, "macro-keyword"
    for rx, why in _NOISE:
        if rx.search(title):
            return False, why
    return True, "kept"


def apply(items, budget=BUDGET, verbose=False):
    """-> (kept, dropped). Deterministic: same input, same output."""
    survivors, dropped, seen = [], [], set()
    for it in items:
        ok, why = classify(it)
        if not ok:
            dropped.append((it, why))
            continue
        key = _norm(it.get("title"))
        if key in seen:
            dropped.append((it, "duplicate headline"))
            continue
        seen.add(key)
        survivors.append(it)

    # Highest priority first, most recent first within a tier.
    survivors.sort(key=lambda i: (-score(i), i.get("published") or ""))
    scale = budget / sum(REGION_QUOTA.values())
    quota = {r: max(1, round(n * scale)) for r, n in REGION_QUOTA.items()}
    kept, per_source, per_region, overflow = [], Counter(), Counter(), []
    for it in survivors:
        src = it.get("source") or it.get("kind") or "?"
        r = region(it)
        if per_region[r] >= quota[r]:
            overflow.append((it, f"{r} quota {quota[r]}"))
            continue
        if per_source[src] >= PER_SOURCE_CAP:
            overflow.append((it, f"source cap {PER_SOURCE_CAP}"))
            continue
        per_source[src] += 1
        per_region[r] += 1
        kept.append(it)
    # Any quota the other region left unused is worth filling rather than wasting.
    if len(kept) < budget:
        for it, why in list(overflow):
            if len(kept) >= budget:
                break
            if "quota" in why and per_source[it.get("source") or "?"] < PER_SOURCE_CAP:
                per_source[it.get("source") or "?"] += 1
                kept.append(it)
                overflow.remove((it, why))
    dropped += overflow

    if verbose:
        for why, n in Counter(w for _, w in dropped).most_common():
            print(f"  -{n:4} {why}", file=sys.stderr)
        print(f"  kept score mix: "
              f"{dict(Counter(score(i) for i in kept).most_common())}", file=sys.stderr)
    return kept, dropped


if __name__ == "__main__":
    import db as dbm
    import triage
    db = dbm.connect()
    triage.MAX_ITEMS = 5000
    items = triage.gather_items(db, 48)
    kept, dropped = apply(items, verbose=True)
    print(f"in={len(items)} kept={len(kept)} dropped={len(dropped)}")
    if "--show-dropped" in sys.argv:
        for it, why in dropped[:50]:
            print(f"  DROP [{why}] {it['title'][:74]}")
    if "--show-kept" in sys.argv:
        for it in kept:
            print(f"  KEEP {score(it):3} [{it['kind']:11}] {it['title'][:70]}")
