#!/usr/bin/env python3
"""Orchestrator for the 07:00 JST brief. Invoked by daily-feeds.timer at 21:10 UTC.

Preflight matters more than it looks: the claude-cli OAuth token is ~8h, so this run lands
after a daytime token has expired and depends on unattended refresh rotation. If auth is dead
the brief must fail *loudly* — a silent no-brief morning is the worst possible outcome, because
it is indistinguishable from a quiet market.

Usage: run.py [--date YYYY-MM-DD] [--skip-dives] [--floor 55] [--max-deep 3]
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import db as dbm

HERE = Path(__file__).resolve().parent
PY = sys.executable
# The audio stage needs piper, which lives in the repo venv rather than system python. Every
# other stage is stdlib-only and runs on whatever interpreter started this file.
VENV_PY = HERE.parent / ".venv/bin/python"


def stage(name, args, brief_id, timeout=3600, fatal=True, interpreter=None):
    """Run a stage, streaming its output line-by-line.

    Deliberately not subprocess.run(capture_output=True): that buffers everything until the
    child exits, so a triage stage that takes 25 minutes writes nothing to run.log for 25
    minutes. This log is the only window into an unattended 21:10 UTC run, so progress has to
    appear as it happens. Output is still retained, to quote back into briefs.error on failure.

    fatal=False marks a stage whose failure must not fail the brief — used for audio, which is
    an enhancement. A morning with text and no audio is a working brief; a morning with neither
    because the TTS voice file went missing is not.
    """
    t0 = time.time()
    print(f"\n=== {name} ===", flush=True)
    tail = []
    p = subprocess.Popen([str(interpreter or PY), "-u", str(HERE / args[0])] + args[1:],
                         cwd=HERE, text=True, env={**os.environ, "PYTHONPATH": str(HERE)},
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
    try:
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            tail.append(line)
            del tail[:-60]
        rc = p.wait(timeout=max(1, timeout - (time.time() - t0)))
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        rc = -9
        tail.append(f"stage exceeded {timeout}s and was killed\n")
    print(f"--- {name}: {'ok' if rc == 0 else f'EXIT {rc}'} in {time.time() - t0:.0f}s",
          flush=True)
    if rc != 0:
        if not fatal:
            print(f"    ({name} is non-fatal — the brief still publishes)", flush=True)
            return "".join(tail)
        with dbm.connect() as db:
            dbm.fail_brief(db, brief_id,
                           f"{name} failed (exit {rc}): {''.join(tail).strip()[-500:]}")
        sys.exit(f"{name} failed — brief marked error and visible on the dashboard")
    return "".join(tail)


def preflight(brief_id):
    """Prove the claude CLI can actually complete a turn before committing to the run."""
    try:
        p = subprocess.run(["claude", "-p", "Reply with exactly: READY",
                            "--model", "sonnet", "--allowedTools", ""],
                           capture_output=True, text=True, timeout=180)
        ok = p.returncode == 0 and "READY" in p.stdout
        detail = (p.stderr or p.stdout).strip()[-300:]
    except Exception as e:
        ok, detail = False, f"{type(e).__name__}: {e}"
    if not ok:
        with dbm.connect() as db:
            dbm.fail_brief(db, brief_id, f"claude-cli preflight failed — re-auth the CLI. {detail}")
        sys.exit(f"preflight failed: {detail}")
    print("preflight: claude-cli usable")


def main():
    def opt(flag, default):
        return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default

    date_jst = opt("--date", None)
    date_args = ["--date", date_jst] if date_jst else []
    t0 = time.time()

    with dbm.connect() as db:
        brief_id = dbm.get_or_create_brief(db, date_jst)
        db.execute("UPDATE briefs SET status='pending', error=NULL, started_at=? WHERE id=?",
                   (dbm.now_utc(), brief_id))
        db.commit()
    print(f"brief={brief_id} date={date_jst or dbm.today_jst()}")

    preflight(brief_id)
    stage("fetch", ["fetch.py"] + date_args, brief_id, timeout=600)
    stage("market", ["market.py"] + date_args, brief_id, timeout=600)
    # --force is required to re-run a date whose dives already completed, because re-triaging
    # CASCADE-deletes them. Absent it, a repeat run stops rather than destroying finished work.
    stage("triage", ["triage.py"] + date_args
          + ["--floor", opt("--floor", "55"), "--max-deep", opt("--max-deep", "3")]
          + (["--force"] if "--force" in sys.argv else []),
          brief_id, timeout=2400)

    if "--skip-dives" in sys.argv:
        print("\n--skip-dives: stopping after triage")
        return
    stage("dives", ["dive.py"] + date_args, brief_id, timeout=2700)

    # Audio last and non-fatal: dives have already published by this point, so the page is
    # complete with or without it. Skipped rather than failed when the venv is absent, because
    # "piper is not installed" is a setup fact, not a broken morning.
    if "--skip-audio" in sys.argv:
        print("\n--skip-audio: stopping after dives")
    elif not VENV_PY.exists():
        print(f"\naudio: skipped — no interpreter at {VENV_PY} "
              f"(uv venv .venv && uv pip install piper-tts)")
    else:
        stage("audio", ["speech.py"] + date_args, brief_id, timeout=1800,
              fatal=False, interpreter=VENV_PY)

    print(f"\ntotal {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
