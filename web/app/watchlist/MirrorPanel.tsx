"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { SyncRun } from "@/lib/types";

type Mirror = { total: number; asof: string | null; withEnglish: number };
type Payload = { mirror: Mirror; runs: SyncRun[] };

const STATUS: Record<string, string> = {
  ok: "bg-on-soft text-on",
  error: "bg-off-soft text-off",
  running: "bg-amb-soft text-amb",
  skipped: "bg-field text-muted",
};

/** The mirror's operational view: is the data current, when did it last refresh, what changed,
 *  and a way to refresh it now without SSH. The weekly timer is the normal path — this panel
 *  exists so a silently failed week is *visible*, which is the whole risk of moving a dataset
 *  onto a schedule.
 */
export function MirrorPanel() {
  const [data, setData] = useState<Payload | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/tickers/sync", { cache: "no-store" });
      const j: Payload = await r.json();
      setData(j);
      // A live run means the numbers are about to change; poll until it settles, then stop.
      // Nothing here polls at rest — a dashboard left open overnight should be silent.
      const live = j.runs.some((x) => x.status === "running" && !x.stalled);
      if (timer.current) clearTimeout(timer.current);
      timer.current = live ? setTimeout(load, 3000) : null;
      setBusy(live);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load]);

  const syncNow = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/tickers/sync", { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error ?? "could not start the sync");
      await load();
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };

  const runs = data?.runs ?? [];
  const last = runs.find((r) => r.status !== "skipped") ?? runs[0];

  return (
    <div className="mt-4 rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="t-label">Ticker mirror</h3>
        {data && (
          <p className="t-meta">
            {data.mirror.total.toLocaleString()} TSE listings · JPX {fmtAsof(data.mirror.asof)} ·{" "}
            {data.mirror.withEnglish.toLocaleString()} with English names
          </p>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={syncNow}
            disabled={busy}
            className="t-ui rounded-md bg-ink px-3 py-1.5 font-medium text-cream hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "syncing…" : "Sync now"}
          </button>
          <button
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="t-meta rounded-md border border-line px-2.5 py-1 hover:bg-wash"
          >
            {open ? "hide runs" : `runs · ${runs.length}`}
          </button>
        </div>
      </div>

      <p className="t-meta mt-1.5">
        Refreshes itself every Monday 20:00 UTC (<code>daily-feeds-tickers.timer</code>). JPX
        stamps the file month-end, so most weeks record no change.
        {last && (
          <>
            {" "}
            Last run {fmtWhen(last.startedAt)} — <RunSummary run={last} />.
          </>
        )}
      </p>

      {err && <p className="t-meta mt-1.5 text-off">{err}</p>}

      {open && (
        <ul className="mt-3 space-y-1 border-t border-line-soft pt-3">
          {runs.length === 0 && <li className="t-meta">No runs recorded yet.</li>}
          {runs.map((r) => (
            <li key={r.id} className="flex flex-wrap items-baseline gap-x-2">
              <span
                className={`rounded px-1.5 py-px text-[10px] font-semibold tracking-wide uppercase ${
                  STATUS[r.stalled ? "error" : r.status] ?? STATUS.skipped
                }`}
              >
                {r.stalled ? "stalled" : r.status}
              </span>
              <span className="t-meta font-mono">{fmtWhen(r.startedAt)}</span>
              <span className="t-meta">{r.trigger}</span>
              <span className="t-meta text-ink-soft">
                <RunSummary run={r} />
              </span>
              {r.error && <span className="t-meta text-off">{r.error}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** What a run actually did. "no change" is a real, useful outcome here, not a missing value. */
function RunSummary({ run }: { run: SyncRun }) {
  if (run.status === "running") return <>in progress</>;
  if (run.status === "skipped") return <>skipped</>;
  if (run.status === "error") return <>failed</>;
  const parts = [
    run.added ? `+${run.added} new` : null,
    run.changed ? `${run.changed} changed` : null,
    run.delisted ? `−${run.delisted} delisted` : null,
    run.namesAdded ? `+${run.namesAdded} English names` : null,
  ].filter(Boolean);
  return <>{parts.length ? parts.join(", ") : "no change"}</>;
}

function fmtAsof(asof: string | null): string {
  if (!asof || !/^\d{8}$/.test(asof)) return asof ?? "—";
  return `${asof.slice(0, 4)}-${asof.slice(4, 6)}-${asof.slice(6)}`;
}

/** Times render in the reader's own zone — this panel is read by one person, on one laptop. */
function fmtWhen(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
