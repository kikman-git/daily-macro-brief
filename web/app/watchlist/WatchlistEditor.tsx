"use client";

import { useRef, useState } from "react";
import type { TickerHit, WatchRow } from "@/lib/types";
import { MirrorPanel } from "./MirrorPanel";
import { TickerPicker } from "./TickerPicker";

type Draft = {
  id?: number;
  ticker: string;
  name: string;
  market: string;
  sector: string;
  status: "hold" | "watch";
  betaTag: "high" | "mid" | "low";
  drivers: string;
  thesis: string;
  /** Set when the fields came from the JPX mirror — shown for confirmation, never stored. */
  nameEn?: string | null;
  /** No ticker resolved yet: the form shows the search box instead of the identity fields. */
  picking?: boolean;
};

const BLANK: Draft = {
  ticker: "",
  name: "",
  market: "",
  sector: "",
  status: "watch",
  betaTag: "high",
  drivers: "",
  thesis: "",
  picking: true,
};

const toDraft = (r: WatchRow): Draft => ({
  id: r.id,
  ticker: r.ticker,
  name: r.name,
  market: r.market ?? "",
  sector: r.sector ?? "",
  status: r.status,
  betaTag: r.betaTag,
  drivers: r.drivers.join(", "),
  thesis: r.thesis ?? "",
});

const BETA: Record<string, string> = {
  high: "bg-off-soft text-off",
  mid: "bg-field text-muted",
  low: "bg-on-soft text-on",
};

const label = "t-label mb-1 block";
const field =
  "t-ui w-full rounded-md border border-line bg-surface px-2.5 py-1.5 focus:border-accent focus:outline-none";
/* Filled buttons use ink rather than the terracotta accent: white on #c15f3c is 4.2:1 and white
   on the dark theme's lighter accent is 2.6:1, so an accent-filled button cannot clear AA in
   both themes. Ink/cream is 12.9:1 either way. */
const primary = "t-ui rounded-md bg-ink px-3 py-1.5 font-medium text-cream hover:opacity-90";
const secondary = "t-ui rounded-md border border-line px-3 py-1.5 text-muted hover:bg-wash";

export function WatchlistEditor({
  initialRows,
  initialSectors,
}: {
  initialRows: WatchRow[];
  initialSectors: string[];
}) {
  const [rows, setRows] = useState(initialRows);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [details, setDetails] = useState(false);
  const [sectors, setSectors] = useState(initialSectors.join(", "));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const driversRef = useRef<HTMLInputElement>(null);

  const refresh = async () => {
    const r = await fetch("/api/watchlist", { cache: "no-store" });
    const j = await r.json();
    setRows(j.rows);
  };

  /** `again` keeps the form open on a fresh blank draft — entering a book of ten names is one
   *  pass (type, Enter, ⌘Enter) instead of ten trips through the Add button. */
  const save = async (again = false) => {
    if (!draft) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch("/api/watchlist", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          ...draft,
          drivers: draft.drivers.split(",").map((d) => d.trim()).filter(Boolean),
        }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? "save failed");
      setDraft(again ? { ...BLANK } : null);
      setDetails(false);
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  /** A mirror hit fills everything the JPX file knows. Beta is a suggestion from the TOPIX size
   *  class; sector is JPX's 33業種, which is factual but coarser than the tags the dives read
   *  ("semis"), so both stay editable right below.
   *
   *  Resolving a ticker that is already on the list turns the draft into an *edit* of that row.
   *  Saving a new draft over an existing ticker would otherwise upsert by ticker and replace the
   *  drivers and thesis already written for it with this draft's empty ones.
   */
  const pick = (h: TickerHit) => {
    const existing = rows.find((r) => r.ticker === h.code);
    const fresh: Draft = {
      ...(draft ?? BLANK),
      name: h.nameJa,
      market: h.market,
      sector: h.sector ?? "",
      betaTag: h.betaHint,
    };
    setDraft({
      ...(existing ? toDraft(existing) : fresh),
      ticker: h.code,
      nameEn: h.nameEn,
      picking: false,
    });
    setDetails(false);
    setTimeout(() => driversRef.current?.focus(), 0);
  };

  const manual = (raw: string) => {
    const existing = rows.find((r) => r.ticker === raw.trim());
    setDraft({
      ...(existing ? toDraft(existing) : { ...(draft ?? BLANK), ticker: raw.trim(), name: "" }),
      nameEn: null,
      picking: false,
    });
    setDetails(true);
  };

  const remove = async (id: number, ticker: string) => {
    if (!confirm(`Remove ${ticker} from the watchlist?`)) return;
    setBusy(true);
    await fetch(`/api/watchlist/${id}`, { method: "DELETE" });
    await refresh();
    setBusy(false);
  };

  const saveSectors = async () => {
    setBusy(true);
    setSaved(null);
    await fetch("/api/watchlist", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        settings: { sectors: sectors.split(",").map((s) => s.trim()).filter(Boolean) },
      }),
    });
    setBusy(false);
    setSaved("saved");
    setTimeout(() => setSaved(null), 2000);
  };

  const held = rows.filter((r) => r.status === "hold");
  const watched = rows.filter((r) => r.status === "watch");

  const group = (title: string, list: WatchRow[]) =>
    list.length > 0 && (
      <div className="mb-6">
        <h3 className="t-label mb-2">
          {title} · {list.length}
        </h3>
        <ul className="space-y-2">
          {list.map((r) => (
            <li
              key={r.id}
              className="flex items-start gap-3 rounded-lg border border-line bg-surface px-3.5 py-2.5"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[14px] font-medium text-ink">{r.ticker}</span>
                  <span className="text-[15px] text-ink-soft">{r.name}</span>
                  <span
                    className={`rounded px-1.5 py-px text-[10px] font-semibold tracking-wide uppercase ${BETA[r.betaTag]}`}
                  >
                    β {r.betaTag}
                  </span>
                  {r.market && <span className="t-meta">{r.market}</span>}
                </div>
                {r.sector && <p className="t-meta mt-0.5">{r.sector}</p>}
                {r.drivers.length > 0 && (
                  <p className="mt-1 flex flex-wrap gap-1">
                    {r.drivers.map((d) => (
                      <span key={d} className="rounded bg-field px-1.5 py-px font-mono text-[11px] text-muted">
                        {d}
                      </span>
                    ))}
                  </p>
                )}
                {r.thesis && <p className="t-meta mt-1.5 leading-snug">{r.thesis}</p>}
              </div>
              <div className="flex shrink-0 gap-1">
                <button
                  onClick={() => setDraft(toDraft(r))}
                  className="t-meta rounded border border-line px-2 py-1 hover:bg-wash"
                >
                  edit
                </button>
                <button
                  onClick={() => remove(r.id, r.ticker)}
                  className="t-meta rounded border border-line px-2 py-1 hover:bg-off-soft hover:text-off"
                >
                  ×
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    );

  return (
    <>
      {rows.length === 0 && !draft && (
        <div className="mb-6 rounded-xl border border-dashed border-line bg-surface p-5">
          <p className="font-serif text-[17px] text-ink">The watchlist is empty.</p>
          <p className="t-ui mt-1.5 max-w-[70ch] leading-relaxed text-muted">
            Without names, dives reason in sectors and Growth250 beta rather than inventing
            tickers — correct, but name-level transmission is the part a subscription can&apos;t
            give you either. Add what you actually hold.
          </p>
        </div>
      )}

      {group("Holding", held)}
      {group("Watching", watched)}

      {draft ? (
        <div
          className="mb-6 rounded-xl border border-accent bg-surface p-4"
          onKeyDown={(e) => {
            // Bubbled from whichever field has focus. Plain Enter belongs to the picker's
            // listbox, so the shortcut takes a modifier.
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !busy && !draft.picking) {
              e.preventDefault();
              void save();
            }
          }}
        >
          <p className="t-label mb-3 text-accent-deep">
            {draft.id ? `Edit ${draft.ticker}` : "New position"}
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {draft.picking ? (
              <div className="sm:col-span-2">
                <TickerPicker
                  onPick={pick}
                  onManual={manual}
                  autoFocus
                  taken={new Set(rows.map((r) => r.ticker))}
                />
              </div>
            ) : (
              <div className="sm:col-span-2 flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-lg border border-line-soft bg-wash px-3 py-2">
                <span className="font-mono text-[14px] font-medium text-ink">{draft.ticker}</span>
                <span className="text-[15px] text-ink">{draft.name || "—"}</span>
                {draft.nameEn && <span className="t-meta">{draft.nameEn}</span>}
                <span className="t-meta">
                  {[draft.market, draft.sector].filter(Boolean).join(" · ")}
                </span>
                <span className="ml-auto flex gap-1">
                  <button
                    type="button"
                    onClick={() => setDetails((v) => !v)}
                    aria-expanded={details}
                    className="t-meta rounded border border-line px-2 py-0.5 hover:bg-surface"
                  >
                    {details ? "hide fields" : "edit fields"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setDraft({ ...draft, picking: true })}
                    className="t-meta rounded border border-line px-2 py-0.5 hover:bg-surface"
                  >
                    search again
                  </button>
                </span>
              </div>
            )}

            {details && !draft.picking && (
              <>
                <div>
                  <label className={label} htmlFor="ticker">
                    Ticker
                  </label>
                  <input
                    id="ticker"
                    className={field}
                    placeholder="6920"
                    value={draft.ticker}
                    onChange={(e) => setDraft({ ...draft, ticker: e.target.value })}
                  />
                </div>
                <div>
                  <label className={label} htmlFor="name">
                    Name
                  </label>
                  <input
                    id="name"
                    className={field}
                    placeholder="レーザーテック"
                    value={draft.name}
                    onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  />
                </div>
                <div>
                  <label className={label} htmlFor="market">
                    Market
                  </label>
                  <input
                    id="market"
                    className={field}
                    placeholder="TSE Growth / Prime / Standard"
                    value={draft.market}
                    onChange={(e) => setDraft({ ...draft, market: e.target.value })}
                  />
                </div>
                <div>
                  <label className={label} htmlFor="sector">
                    Sector
                  </label>
                  <input
                    id="sector"
                    className={field}
                    placeholder="semis / semi equipment"
                    value={draft.sector}
                    onChange={(e) => setDraft({ ...draft, sector: e.target.value })}
                  />
                  <p className="t-meta mt-1">
                    JPX&apos;s 33業種 when it came from the mirror — overwrite it with your own tag
                    if the dives read better for it.
                  </p>
                </div>
              </>
            )}
            <div>
              <label className={label} htmlFor="status">
                Status
              </label>
              <select
                id="status"
                className={field}
                value={draft.status}
                onChange={(e) => setDraft({ ...draft, status: e.target.value as Draft["status"] })}
              >
                <option value="hold">hold — I own it</option>
                <option value="watch">watch — candidate</option>
              </select>
            </div>
            <div>
              <label className={label} htmlFor="beta">
                Beta tag
              </label>
              <select
                id="beta"
                className={field}
                value={draft.betaTag}
                onChange={(e) => setDraft({ ...draft, betaTag: e.target.value as Draft["betaTag"] })}
              >
                <option value="high">high</option>
                <option value="mid">mid</option>
                <option value="low">low</option>
              </select>
              <p className="t-meta mt-1">
                Pre-set from the TOPIX size class on a mirror pick — a guess about size, not a
                measured beta.
              </p>
            </div>
            <div className="sm:col-span-2">
              <label className={label} htmlFor="drivers">
                Drivers <span className="normal-case opacity-80">— comma separated</span>
              </label>
              <input
                id="drivers"
                ref={driversRef}
                className={field}
                placeholder="SOX, USDJPY, AI capex"
                value={draft.drivers}
                onChange={(e) => setDraft({ ...draft, drivers: e.target.value })}
              />
              <p className="t-meta mt-1">
                What actually moves this name. Dives use these to connect a macro event to it.
              </p>
            </div>
            <div className="sm:col-span-2">
              <label className={label} htmlFor="thesis">
                Thesis
              </label>
              <textarea
                id="thesis"
                rows={2}
                className={field}
                placeholder="One line on why you care."
                value={draft.thesis}
                onChange={(e) => setDraft({ ...draft, thesis: e.target.value })}
              />
            </div>
          </div>
          {err && <p className="t-meta mt-2 text-off">{err}</p>}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              onClick={() => save()}
              disabled={busy || draft.picking}
              className={`${primary} disabled:opacity-50`}
            >
              {busy ? "saving…" : "Save"}
            </button>
            {!draft.id && (
              <button
                onClick={() => save(true)}
                disabled={busy || draft.picking}
                className={`${secondary} disabled:opacity-50`}
              >
                Save &amp; add another
              </button>
            )}
            <button
              onClick={() => {
                setDraft(null);
                setErr(null);
              }}
              className={secondary}
            >
              Cancel
            </button>
            <span className="t-meta ml-auto">⌘/Ctrl + Enter saves</span>
          </div>
        </div>
      ) : (
        <button onClick={() => setDraft({ ...BLANK })} className={`${primary} mb-8`}>
          + Add position
        </button>
      )}

      <div className="rounded-xl border border-line bg-surface p-4">
        <label className={label} htmlFor="sectors">
          Sectors of interest
        </label>
        <input
          id="sectors"
          className={field}
          placeholder="semis, defense, domestic retail, shipping, AI capex"
          value={sectors}
          onChange={(e) => setSectors(e.target.value)}
        />
        <p className="t-meta mt-1.5">
          Used when an event has no name-level read-through. Comma separated.
        </p>
        <div className="mt-2.5 flex items-center gap-2">
          <button
            onClick={saveSectors}
            disabled={busy}
            className="t-meta rounded-md border border-line px-2.5 py-1 hover:bg-wash disabled:opacity-50"
          >
            Save sectors
          </button>
          {saved && <span className="t-meta text-on">{saved}</span>}
        </div>
      </div>

      <MirrorPanel />
    </>
  );
}
