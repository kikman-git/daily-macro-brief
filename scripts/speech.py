#!/usr/bin/env python3
"""Stage 5 — spoken versions of the day's analysis.

A dive runs 900-1,600 words, which is five to seven minutes aloud: pre-open commute length.
This stage renders one track per dive plus a roll-up covering the whole morning.

WHY THE DEFAULT ENGINE IS LOCAL
-------------------------------
Gemini TTS was the first choice and it works, but the free-tier quota on this project is
`GenerateRequestsPerDayPerProjectPerModel-FreeTier = 10 requests per day` for
gemini-2.5-flash-preview-tts. One brief needs roughly forty calls, so the API path cannot
produce a single complete morning without billing enabled. Piper runs locally on CPU with no
quota at all, which is the only property that matters for something that has to work at 06:10
every day unattended. `--engine gemini` is still wired up and correct: if billing is ever
enabled it becomes a one-word switch.

The cost of going local is Japanese: Piper voices are monolingual. Measured on a real dive,
CJK is 0.5% of the spoken script (25 short runs), so JA_GLOSS translates the recurring macro
vocabulary and anything left over is dropped — safe in practice because the dives already
gloss their own Japanese inline, e.g. "円買い介入 (yen-buying intervention)".

OTHER THINGS THAT ARE LOAD-BEARING
----------------------------------
* The dive body is NOT fed to a synthesiser as-is. It contains markdown tables, citation URLs
  and emphasis marks, and read literally that produces "h-t-t-p-s colon slash slash".
  `speechify()` turns a dive into something a person would actually say, and `--dry-run` prints
  it so the script can be audited without synthesising anything.
* Chunking is a hard requirement on the Gemini path, not an optimisation. Measured against the
  live key: 600 chars -> 30s of audio, 1,200 -> 47s, and 2,000 returns finishReason=OTHER with
  zero output and no error. On Piper chunking only buys parallelism, so the limit is larger.
* The roll-up reuses the PCM already rendered for each dive rather than re-synthesising the
  text: one short intro plus one title per event, not a second pass over every word.

Usage:
  speech.py [--date YYYY-MM-DD] [--event ID] [--force] [--dry-run]
            [--engine piper|gemini] [--voice NAME] [--jobs N]
"""
import base64
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date as _date
from pathlib import Path

import db as dbm

ENGINE = "piper"
JOBS = 3                  # 4 cores; leave one for the box
TIMEOUT = 300
RETRIES = 3

PIPER_VOICE = "en_US-ryan-high"          # 2.0x realtime, the most natural English Piper voice
PIPER_DIR = Path(os.environ.get("PIPER_VOICES",
                                os.path.expanduser("~/.local/share/piper-voices")))
PIPER_CHUNK = 4000        # no API ceiling; sized purely so 3 workers stay busy

GEMINI_MODEL = "gemini-2.5-flash-preview-tts"
GEMINI_VOICE = "Charon"   # the "informative" prebuilt voice
GEMINI_CHUNK = 1100       # measured ceiling is under 2,000; see the module docstring
GEMINI_RATE = 24000
GEMINI_STYLE = (
    "Read the following aloud as a calm, measured market-briefing narrator. Even pace, clear "
    "diction, a short pause at each full stop. Read only the text; add no words of your own.\n\n"
)
ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent?key={key}")


class Empty(Exception):
    """A candidate came back with no audio — the symptom of an over-long Gemini chunk."""


# --------------------------------------------------------------------------- text -> speech

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^([-*+]|\d+[.)])\s+(.*)$")
HR = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
TABLE_SEP = re.compile(r"^\|[\s:|-]+\|$")
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]+")

CURRENCY = {"¥": "yen", "$": "dollars", "€": "euros", "£": "pounds"}
MAGNITUDE = {"trn": "trillion", "tn": "trillion", "bn": "billion", "mn": "million",
             "bil": "billion", "k": "thousand"}

# Symbol, amount, optional range, optional magnitude — all in ONE pattern, because handling them
# as separate rules is what turned "$36.58bn" into "36.58 dollarsbn" and "¥11-12trn" into
# "11 yen-12trn": the currency rule consumed the digits and left the suffix stranded.
CUR_RE = re.compile(
    r"([¥$€£])\s*([\d,]+(?:\.\d+)?)"
    r"(?:\s*[–—-]\s*([\d,]+(?:\.\d+)?))?"
    # \s* lives INSIDE the optional group: outside it, "$853 volume" consumed the space while
    # matching no magnitude and emitted "853 dollarsvolume".
    r"(?:\s*(trn|tn|bn|mn|bil|trillion|billion|million))?\b", re.I)


def _cur(m):
    sym, a, b, mag = m.groups()
    mag = MAGNITUDE.get((mag or "").lower(), (mag or "").lower())
    amount = f"{a} to {b}" if b else a
    return " ".join(x for x in (amount, mag, CURRENCY[sym]) if x)


# No leading articles: these appear mid-sentence after one as often as not, and "the bundle's
# the Nikkei field" is worse than a bare name.
TICKERS = {"^N225": "Nikkei 225", "^TPX": "TOPIX", "^GSPC": "S and P 500",
           "^SOX": "SOX", "^VIX": "VIX", "JPY=X": "dollar yen"}

# Respellings, and only ones that survive verification IN A REAL SENTENCE.
#
# "Nikkay" is deliberately absent. Piper renders "Nikkei" as roughly "Nik", and in an isolated
# probe ("The Nikkay 225 closed higher.") the respelling transcribed back correctly — but in the
# actual dive sentence it still came out "Nik 225". Phonemisation is context-sensitive, so a
# single-phrase check proves nothing; shipping it would have put a misspelling into script_txt
# for no audible gain. TOPIX has the same status: it reads as "topics", still parses in context,
# and no verified fix exists.
#
# What is here is ordinary-English expansion, which needs no phonetic gamble: Piper said "TSC"
# for TSE, and full words cannot be mispronounced in the same way.
SAY_AS = [
    (re.compile(r"\bTSE\b"), "Tokyo Stock Exchange"),
]

# The recurring Japanese macro vocabulary, longest first so 円買い介入 is not eaten by 円安.
JA_GLOSS = {
    "外国為替平衡操作": "foreign exchange intervention operations",
    "日米通貨同盟": "a Japan-US currency alliance",
    "レートチェック": "a rate check",
    "日経平均株価": "the Nikkei average",
    "東証グロース": "TSE Growth",
    "円買い介入": "yen-buying intervention",
    "為替介入": "currency intervention",
    "協調介入": "coordinated intervention",
    "上方修正": "an upward revision",
    "下方修正": "a downward revision",
    "金融緩和": "monetary easing",
    "金融引き締め": "monetary tightening",
    "信用買い": "margin buying",
    "日経平均": "the Nikkei",
    "輸出株": "exporters",
    "財務省": "the Ministry of Finance",
    "日銀": "the Bank of Japan",
    "内需": "domestic demand",
    "円安": "yen weakness",
    "円高": "yen strength",
    "利上げ": "a rate hike",
    "利下げ": "a rate cut",
    # Titles, so "三村財務官 said" keeps a subject after the name itself is stripped. Personal
    # names are lost — transliterating them needs a dictionary this stage has no business
    # carrying, and the dives name the same people in English elsewhere.
    "官房長官": "the Chief Cabinet Secretary",
    "財務相": "the Finance Minister",
    "財務官": "the Vice Finance Minister",
    "首相": "the Prime Minister",
    "総裁": "the Governor",
}
JA_RE = re.compile("|".join(sorted(map(re.escape, JA_GLOSS), key=len, reverse=True)))
# 「…」 spans are quoted Japanese headlines cited as provenance. Glossing one word-by-word
# produced "The average 202 Yen strength 63,957" out of 「日経平均株価、反発 終値は202円高の6万3957円」,
# which is not a translation, it is noise — and the surrounding English already states the fact.
JA_QUOTE = re.compile(r"[「『][^」』]{0,300}[」』]")


def _ja(m):
    """円高 alone is "yen strength"; 202円高 means "202 yen higher". The gloss is context-blind
    without this guard, and got the direction of a Nikkei move exactly backwards."""
    term = m.group(0)
    if term in ("円高", "円安"):
        prev = m.string[m.start() - 1] if m.start() else ""
        if prev.isdigit():
            return " yen higher" if term == "円高" else " yen lower"
    return JA_GLOSS[term]

SUBS = [
    (CUR_RE, _cur),
    (re.compile(r"([\d,.]+)\s*(trn|tn|bn|mn)\b", re.I),
     lambda m: f"{m.group(1)} {MAGNITUDE[m.group(2).lower()]}"),
    (re.compile("|".join(re.escape(k) for k in TICKERS)), lambda m: TICKERS[m.group(0)]),
    *SAY_AS,
    (re.compile(r"\bBOJ\b"), "Bank of Japan"),
    (re.compile(r"\bMOF\b"), "Ministry of Finance"),
    (re.compile(r"\bJGBs\b"), "J G Bs"),
    (re.compile(r"\bJGB\b"), "J G B"),
    (re.compile(r"\bFOMC\b"), "F O M C"),
    (re.compile(r"\b(CPI|PPI|GDP|PMI|ETF|BOE|ECB|PBOC|ESF|FIMA|UST)s?\b"),
     lambda m: " ".join(m.group(1)) + ("s" if m.group(0).endswith("s") else "")),
    (re.compile(r"\bUSD/?JPY\b", re.I), "dollar yen"),
    (re.compile(r"\bYoY\b", re.I), "year on year"),
    (re.compile(r"\bMoM\b", re.I), "month on month"),
    (re.compile(r"\bQoQ\b", re.I), "quarter on quarter"),
    (re.compile(r"(\d)\s*bps\b"), r"\1 basis points"),
    (re.compile(r"(\d)\s*bp\b"), r"\1 basis point"),
    (re.compile(r"(\d(?:\.\d+)?)\s*pp\b"), r"\1 percentage points"),
    (re.compile(r"\(bundle\)"), "from the market snapshot"),
    # Piper says "Aug" as "awg", so "the 3 Aug close, not 4 Aug" was heard as "the three all
    # close, not four all". Dates are material in a market brief — spell the months out.
    (re.compile(r"\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\b\.?"),
     lambda m: {"jan": "January", "feb": "February", "mar": "March", "apr": "April",
                "jun": "June", "jul": "July", "aug": "August", "sep": "September",
                "sept": "September", "oct": "October", "nov": "November",
                "dec": "December"}[m.group(1).lower()]),
    (re.compile(r"\bvol\b", re.I), "volatility"),
    (re.compile(r"\b(\d+)d\b"), r"\1-day"),
    # A ticker read as "two thousand five hundred sixteen" is not a ticker. Digits, spaced.
    (re.compile(r"\b(\d{4})\.T\b"), lambda m: " ".join(m.group(1))),
    # Ranges before dashes-as-punctuation, so "30-31 July" survives the next rule intact.
    (re.compile(r"(\d)\s*[–—]\s*(?=\d)"), r"\1 to "),
    (re.compile(r"(?<![\d\w])[−–]\s*(?=[\d.])"), "minus "),
    (re.compile(r"\s+[—–]\s+|\s+-\s+"), ", "),         # remaining dashes are punctuation
]


def clean_inline(t, strip_cjk=False):
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)   # links keep their text, lose the URL
    t = re.sub(r"<https?://[^>]+>", "", t)
    t = re.sub(r"https?://\S+", "", t)                 # bare URLs are unspeakable
    t = re.sub(r"\*\*|\*|`|~~", "", t)                 # emphasis and code marks
    t = re.sub(r",?\s*direct URL not found", "", t, flags=re.I)   # citation plumbing, not prose
    t = JA_QUOTE.sub("", t)
    t = JA_RE.sub(_ja, t)
    # The dives gloss their own Japanese — "円買い介入 (yen-buying intervention)" — so glossing
    # it again yields a stutter. Collapse "X (X)" back to "X".
    t = re.sub(r"([\w][\w \-]{2,60}?)\s*[（(]\s*\1\s*[)）]", r"\1", t, flags=re.I)
    for pat, rep in SUBS:
        t = pat.sub(rep, t)
    if strip_cjk:
        # Whatever the gloss missed. Safe because the dives write their own inline translation;
        # feeding raw CJK to an English voice produces noise, not information.
        t = CJK.sub("", t)
    # Anything alphanumeric-free left inside brackets is the residue of a dropped Japanese
    # citation — "(— )" is what survived 「…」— 日本経済新聞, direct URL not found.
    t = re.sub(r"[（(][^A-Za-z0-9]*[)）]", "", t)
    t = re.sub(r"\s+([.,;:)])", r"\1", t)
    t = re.sub(r",\s*,", ",", t)
    t = re.sub(r"\s+([.,])", r"\1", t)
    return re.sub(r"[ \t]+", " ", t).strip()


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _blocks(md):
    """Markdown -> a list of (kind, payload). Same scope as the web renderer, no more."""
    lines = md.replace("\r", "").split("\n")
    out, i = [], 0
    while i < len(lines):
        t = lines[i].strip()
        if not t or HR.match(t):
            i += 1
            continue
        h = HEADING.match(t)
        if h:
            out.append(("head", h.group(2).strip()))
            i += 1
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if t.startswith("|") and TABLE_SEP.match(nxt):
            head, rows = _cells(t), []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            out.append(("table", (head, rows)))
            continue
        if BULLET.match(t):
            items = []
            while i < len(lines):
                m = BULLET.match(lines[i].strip())
                if not m:
                    break
                txt = m.group(2)
                i += 1
                while (i < len(lines) and lines[i].strip()
                       and not BULLET.match(lines[i].strip())
                       and not lines[i].strip().startswith(("#", ">", "|"))):
                    txt += " " + lines[i].strip()
                    i += 1
                items.append(txt)
            out.append(("list", items))
            continue
        if t.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(("para", " ".join(buf)))
            continue
        buf = [t]
        i += 1
        while (i < len(lines) and lines[i].strip()
               and not lines[i].strip().startswith(("#", ">", "|"))
               and not BULLET.match(lines[i].strip())):
            buf.append(lines[i].strip())
            i += 1
        out.append(("para", " ".join(buf)))
    return out


def _say_table(head, rows, strip_cjk):
    """Narrow tables get verbalised row by row; wide ones get an honest hand-off to the page.

    Reading a six-column grid aloud is worse than not reading it, but silently dropping data is
    worse still — the listener should know something was skipped."""
    if len(head) > 3 or not rows:
        return f"There is a {len(head)}-column table here with {len(rows)} rows; it is on the page."
    said = []
    for r in rows:
        label = clean_inline(r[0], strip_cjk) if r else ""
        rest = [f"{clean_inline(head[j], strip_cjk)} {clean_inline(r[j], strip_cjk)}"
                for j in range(1, min(len(head), len(r))) if r[j].strip()]
        line = label + ((", " + ", ".join(rest)) if rest else "")
        if line.strip():
            said.append(line.rstrip(".") + ".")
    return " ".join(said)


def _sentence(t):
    t = t.strip()
    return t if not t or t[-1] in ".!?:" else t + "."


def speechify(md, strip_cjk=False):
    """A dive body as continuous spoken prose. Paragraph breaks become pauses."""
    parts = []
    for kind, payload in _blocks(md):
        if kind == "head":
            # "Transmission — Japanese equities" reads better as a clause than as a title;
            # clean_inline already turns a spaced em-dash into a comma, so no extra pass here
            # (doing it afterwards is what produced "Transmission , Japanese equities").
            parts.append(_sentence(clean_inline(payload, strip_cjk)))
        elif kind == "table":
            parts.append(_say_table(*payload, strip_cjk))
        elif kind == "list":
            parts.append(" ".join(_sentence(clean_inline(x, strip_cjk)) for x in payload))
        else:
            parts.append(_sentence(clean_inline(payload, strip_cjk)))
    return "\n\n".join(p for p in parts if p.strip())


HORIZONS = {"intraday": "intraday", "1-5d": "one to five days", "1-4w": "one to four weeks",
            "1-3m": "one to three months", "structural": "structural"}


def dive_script(row, strip_cjk=False):
    """Spoken lede from the committed frontmatter, then the body.

    The verdict is the reason to listen at all, so it goes first — the same order the page uses.
    """
    lede = []
    if row["verdict"]:
        lede.append(row["verdict"].replace("-", " ").capitalize() + ".")
    if row["confidence"]:
        lede.append(f"Confidence {row['confidence']}.")
    if row["horizon"]:
        lede.append(f"Horizon {HORIZONS.get(row['horizon'], row['horizon'])}.")
    if row["jp_equity_direction"]:
        lede.append(f"Japanese equities, {row['jp_equity_direction']}.")
    head = f"{_sentence(clean_inline(row['title_en'], strip_cjk))} {' '.join(lede)}".strip()
    return f"{head}\n\n{speechify(row['body_md'] or '', strip_cjk)}"


def chunk_text(text, limit):
    """Split on paragraph then sentence boundaries. Never mid-sentence: a chunk edge is an
    audible seam, so it should land where a speaker would pause anyway."""
    chunks, cur = [], ""

    def flush():
        nonlocal cur
        if cur.strip():
            chunks.append(cur.strip())
        cur = ""

    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(cur) + len(para) + 2 <= limit:
            cur = f"{cur}\n\n{para}" if cur else para
            continue
        flush()
        if len(para) <= limit:
            cur = para
            continue
        for sent in re.split(r"(?<=[.!?])\s+", para):
            if len(cur) + len(sent) + 1 > limit:
                flush()
            # A single sentence over the limit is pathological; send it and let the
            # halve-and-retry in the Gemini engine deal with it rather than cutting mid-word.
            cur = f"{cur} {sent}".strip() if cur else sent
    flush()
    return chunks


# --------------------------------------------------------------------------- engines

class PiperEngine:
    """Local neural TTS. No network, no quota, ~2x realtime per core on this box.

    One shared voice across worker threads: onnxruntime sessions are safe for concurrent Run(),
    and the ryan-high model is 120MB — loading it per thread would cost more than it buys."""

    strip_cjk = True
    chunk = PIPER_CHUNK

    def __init__(self, voice=PIPER_VOICE):
        from piper import PiperVoice          # imported lazily so --engine gemini needs no venv
        path = PIPER_DIR / f"{voice}.onnx"
        if not path.exists():
            raise SystemExit(
                f"missing voice {path}\n"
                f"  .venv/bin/python -m piper.download_voices {voice} --data-dir {PIPER_DIR}")
        self.voice_name = voice
        self._v = PiperVoice.load(str(path))
        self.rate = self._v.config.sample_rate
        self.label = f"piper/{voice}"

    def synth(self, text):
        return b"".join(c.audio_int16_bytes for c in self._v.synthesize(text))


class GeminiEngine:
    """Cloud TTS. Better prosody and it speaks Japanese, but see the quota note in the module
    docstring — unusable on the free tier for a whole brief."""

    strip_cjk = False
    chunk = GEMINI_CHUNK
    rate = GEMINI_RATE

    def __init__(self, voice=GEMINI_VOICE, model=GEMINI_MODEL):
        self.voice_name, self.model, self.key = voice, model, api_key()
        self.label = f"gemini/{model}"

    def _once(self, text):
        body = json.dumps({
            "contents": [{"parts": [{"text": GEMINI_STYLE + text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice_name}}},
            },
        }).encode()
        req = urllib.request.Request(ENDPOINT.format(model=self.model, key=self.key),
                                     data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.load(r)
        cand = (d.get("candidates") or [{}])[0]
        if "content" not in cand:
            raise Empty(f"finishReason={cand.get('finishReason')} for {len(text)} chars")
        return base64.b64decode(cand["content"]["parts"][0]["inlineData"]["data"])

    def synth(self, text, depth=0):
        last = None
        for attempt in range(RETRIES):
            try:
                return self._once(text)
            except Empty as e:
                last = e
                break                  # retrying identical input changes nothing; split instead
            except urllib.error.HTTPError as e:
                last = e
                if e.code in (400, 403, 404):
                    raise
                if e.code == 429:      # daily quota, not a burst — backing off will not help
                    raise RuntimeError(
                        "gemini quota exhausted (free tier is 10 requests/day for this model); "
                        "use --engine piper or enable billing") from e
                time.sleep(3 * (attempt + 1) ** 2)
            except Exception as e:
                last = e
                time.sleep(3 * (attempt + 1) ** 2)
        if isinstance(last, Empty) and depth < 3 and len(text) > 300:
            sents = re.split(r"(?<=[.!?])\s+", text)
            mid = max(1, len(sents) // 2)
            return self.synth(" ".join(sents[:mid]), depth + 1) + \
                self.synth(" ".join(sents[mid:]), depth + 1)
        raise RuntimeError(f"tts failed after {RETRIES}: {type(last).__name__}: {last}")


def api_key():
    k = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if k:
        return k
    cfg = Path("~/.openclaw/openclaw.json").expanduser()
    try:
        k = json.loads(cfg.read_text())["models"]["providers"]["google"]["apiKey"]
    except Exception as e:
        raise SystemExit(f"no Gemini key: set GEMINI_API_KEY or fix {cfg} ({e})")
    if not k:
        raise SystemExit(f"no Gemini key in {cfg}")
    return k


def make_engine(name, voice):
    if name == "piper":
        return PiperEngine(voice or PIPER_VOICE)
    if name == "gemini":
        return GeminiEngine(voice or GEMINI_VOICE)
    raise SystemExit(f"unknown engine: {name} (piper|gemini)")


# --------------------------------------------------------------------------- audio assembly

def silence(engine, seconds):
    return b"\x00\x00" * int(engine.rate * seconds)


def synth_script(engine, text, jobs):
    """Chunks in parallel, reassembled in order. Order matters and as_completed does not keep
    it, so results are placed by index rather than appended."""
    chunks = chunk_text(text, engine.chunk)
    out = [b""] * len(chunks)
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(engine.synth, c): n for n, c in enumerate(chunks)}
        for f in cf.as_completed(futs):
            out[futs[f]] = f.result()
    # A short pad at each seam: chunks end on a full stop, and a synthesiser clips its own tail.
    return silence(engine, 0.15).join(out), len(chunks)


def encode(engine, pcm, path):
    """PCM -> AAC in an .m4a. AAC because it is the one codec every phone browser plays,
    including iOS Safari; +faststart so the player can seek before the file finishes loading."""
    path.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "s16le", "-ar", str(engine.rate), "-ac", "1", "-i", "pipe:0",
         "-c:a", "aac", "-b:a", "48k", "-movflags", "+faststart", str(path)],
        input=pcm, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg exited {p.returncode}: {p.stderr.decode()[-400:]}")
    return path.stat().st_size


def decode(engine, path):
    """An existing track back to PCM, so a cached run can still assemble the roll-up."""
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-f", "s16le", "-ar", str(engine.rate), "-ac", "1", "pipe:1"],
        capture_output=True)
    return p.stdout


# --------------------------------------------------------------------------- persistence

def upsert(db, brief_id, event_id, kind, **cols):
    db.execute(
        "INSERT INTO audio(brief_id,event_id,kind,status,created_at) VALUES(?,?,?,'pending',?) "
        "ON CONFLICT(brief_id,kind,COALESCE(event_id,-1)) DO NOTHING",
        (brief_id, event_id, kind, dbm.now_utc()))
    if cols:
        sets = ",".join(f"{k}=?" for k in cols)
        db.execute(f"UPDATE audio SET {sets} WHERE brief_id=? AND kind=? "
                   "AND COALESCE(event_id,-1)=COALESCE(?,-1)",
                   (*cols.values(), brief_id, kind, event_id))
    db.commit()


def out_path(date_jst, name):
    return Path(dbm.AUDIO_DIR) / date_jst / f"{name}.m4a"


def spoken_date(d):
    try:
        return _date.fromisoformat(d).strftime("%A %-d %B")
    except Exception:
        return d


# --------------------------------------------------------------------------- stage

def main():
    def opt(flag, default, cast=str):
        return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default

    date_jst = opt("--date", None)
    jobs = opt("--jobs", JOBS, int)
    force, dry = "--force" in sys.argv, "--dry-run" in sys.argv

    db = dbm.connect()
    if "--event" in sys.argv:
        eid = opt("--event", None, int)
        row = db.execute("SELECT brief_id FROM events WHERE id=?", (eid,)).fetchone()
        if not row:
            sys.exit(f"no such event: {eid}")
        brief_id, only = row["brief_id"], eid
    else:
        # Never get_or_create here: this stage runs after midnight JST on the winter timetable,
        # and minting a brief from the clock is what produced a phantom empty page once already.
        b = db.execute("SELECT id FROM briefs WHERE date_jst=?", (date_jst,)).fetchone() \
            if date_jst else db.execute(
                "SELECT id FROM briefs ORDER BY date_jst DESC LIMIT 1").fetchone()
        if not b:
            sys.exit("no brief to voice")
        brief_id, only = b["id"], None

    brief = db.execute("SELECT * FROM briefs WHERE id=?", (brief_id,)).fetchone()
    engine_name = opt("--engine", None) or dbm.setting(db, "tts_engine", ENGINE)
    voice = opt("--voice", None) or dbm.setting(db, "tts_voice", None)

    q = ("SELECT d.*, e.id AS event_id, e.title_en, e.rank FROM dives d "
         "JOIN events e ON e.id = d.event_id "
         "WHERE e.brief_id=? AND d.status='done' AND d.body_md IS NOT NULL")
    args = [brief_id]
    if only:
        q += " AND e.id=?"
        args.append(only)
    dives = db.execute(q + " ORDER BY e.rank", args).fetchall()

    if not dives:
        print("no completed dives to voice")
        return

    if dry:
        strip = engine_name == "piper"
        for d in dives:
            s = dive_script(d, strip)
            cs = chunk_text(s, PIPER_CHUNK if strip else GEMINI_CHUNK)
            print(f"\n=== event {d['event_id']}: {len(s)} chars, {len(cs)} chunks "
                  f"({max(len(c) for c in cs)} max) ===\n{s}\n")
        bad = [d["event_id"] for d in dives
               if re.search(r"https?://|\|", dive_script(d, strip))
               or (strip and CJK.search(dive_script(d, strip)))]
        print(f"\nURL / table-pipe / unspoken-CJK leakage: {bad or 'none'}")
        return

    engine = make_engine(engine_name, voice)
    print(f"voicing {len(dives)} dive(s) on {engine.label} @ {engine.rate} Hz, "
          f"{jobs} chunks at a time")
    pcms, t_all = {}, time.time()

    for d in dives:
        eid = d["event_id"]
        dest = out_path(brief["date_jst"], f"event-{eid}")
        have = db.execute("SELECT * FROM audio WHERE brief_id=? AND kind='dive' AND event_id=?",
                          (brief_id, eid)).fetchone()
        if have and have["status"] == "done" and not force and dest.exists():
            print(f"  event {eid}: cached ({have['duration_s']:.0f}s)")
            continue
        script = dive_script(d, engine.strip_cjk)
        upsert(db, brief_id, eid, "dive", status="pending", model=engine.label,
               voice=engine.voice_name, chars=len(script), script_txt=script, error=None,
               created_at=dbm.now_utc())
        try:
            t0 = time.time()
            pcm, n = synth_script(engine, script, jobs)
            size = encode(engine, pcm, dest)
            secs = len(pcm) / 2 / engine.rate
            pcms[eid] = pcm
            upsert(db, brief_id, eid, "dive", status="done", path=str(dest), bytes=size,
                   duration_s=secs, chunks=n)
            print(f"  event {eid}: {secs/60:.1f} min, {n} chunks, {size//1024} KB, "
                  f"{time.time()-t0:.0f}s")
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"[:900]
            upsert(db, brief_id, eid, "dive", status="error", error=msg)
            print(f"  event {eid}: FAIL {msg}", file=sys.stderr)

    if only:
        return

    # ---- roll-up: intro + each dive's already-rendered PCM behind a spoken title.
    dest = out_path(brief["date_jst"], "rollup")
    have = db.execute(
        "SELECT * FROM audio WHERE brief_id=? AND kind='rollup' AND event_id IS NULL",
        (brief_id,)).fetchone()
    if have and have["status"] == "done" and not force and dest.exists() and not pcms:
        print(f"  rollup: cached ({have['duration_s']:.0f}s)")
        return

    ordered = [d for d in dives if d["event_id"] in pcms
               or out_path(brief["date_jst"], f"event-{d['event_id']}").exists()]
    if not ordered:
        print("  rollup: nothing to assemble")
        return

    intro = (f"Macro brief for {spoken_date(brief['date_jst'])}. "
             f"{len(ordered)} deep {'dive' if len(ordered) == 1 else 'dives'} this morning. ")
    if brief["regime_note"]:
        intro += clean_inline(brief["regime_note"], engine.strip_cjk)
    upsert(db, brief_id, None, "rollup", status="pending", model=engine.label,
           voice=engine.voice_name, chars=len(intro), script_txt=intro, error=None,
           created_at=dbm.now_utc())
    try:
        t0 = time.time()
        parts = [engine.synth(intro)]
        for n, d in enumerate(ordered, 1):
            eid = d["event_id"]
            title = f"Item {n}. {_sentence(clean_inline(d['title_en'], engine.strip_cjk))}"
            parts += [silence(engine, 0.8), engine.synth(title), silence(engine, 0.4)]
            parts.append(pcms[eid] if eid in pcms
                         else decode(engine, out_path(brief["date_jst"], f"event-{eid}")))
        pcm = b"".join(parts)
        size = encode(engine, pcm, dest)
        secs = len(pcm) / 2 / engine.rate
        upsert(db, brief_id, None, "rollup", status="done", path=str(dest), bytes=size,
               duration_s=secs, chunks=len(ordered) + 1)
        print(f"  rollup: {secs/60:.1f} min, {size//1024} KB, {time.time()-t0:.0f}s")
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"[:900]
        upsert(db, brief_id, None, "rollup", status="error", error=msg)
        print(f"  rollup: FAIL {msg}", file=sys.stderr)

    print(f"audio stage done in {time.time()-t_all:.0f}s")


if __name__ == "__main__":
    main()
