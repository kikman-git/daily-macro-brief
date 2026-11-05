"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { TickerHit } from "@/lib/types";

type Mirror = { ready: boolean; total: number; asof: string | null; withEnglish: number };

/** Combobox over the local JPX mirror: type a code, a Japanese name, romaji or English and pick
 *  the listing. Selecting fills ticker/name/market/sector/beta in one keystroke, which is the
 *  whole point — four hand-typed fields per position was the manual part.
 *
 *  `onManual` is the escape hatch, and it is not decoration: the mirror covers TSE listings as of
 *  JPX's last month-end file, so a fresh IPO, a foreign line or a private holding has to be
 *  enterable by hand or the form is worse than the one it replaced.
 */
export function TickerPicker({
  onPick,
  onManual,
  autoFocus = false,
  taken,
}: {
  onPick: (hit: TickerHit) => void;
  onManual: (raw: string) => void;
  autoFocus?: boolean;
  /** Tickers already on the watchlist — flagged in the list so you don't add a duplicate. */
  taken: Set<string>;
}) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<TickerHit[]>([]);
  const [mirror, setMirror] = useState<Mirror | null>(null);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const listId = useId();
  const boxRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // The mirror's own state decides whether search is offered at all — an unsynced table must
  // present as "enter it by hand", not as "no such ticker".
  useEffect(() => {
    let live = true;
    fetch("/api/tickers", { cache: "no-store" })
      .then((r) => r.json())
      .then((j) => live && setMirror(j))
      .catch(() => live && setMirror({ ready: false, total: 0, asof: null, withEnglish: 0 }));
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    const term = q.trim();
    if (!term) {
      setHits([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const ctl = new AbortController();
    const t = setTimeout(() => {
      fetch(`/api/tickers?q=${encodeURIComponent(term)}`, {
        cache: "no-store",
        signal: ctl.signal,
      })
        .then((r) => r.json())
        .then((j) => {
          setHits(j.hits ?? []);
          setActive(0);
          setLoading(false);
        })
        .catch(() => {
          /* aborted by the next keystroke, or the route is down — the manual row still works */
        });
    }, 90);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  }, [q]);

  // Arrowing past the visible rows must bring them with it; the list holds 13 and shows ~7.
  useEffect(() => {
    listRef.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  const term = q.trim();
  const manualRow = term.length > 0;
  const rowCount = hits.length + (manualRow ? 1 : 0);

  const choose = (i: number) => {
    if (i < hits.length) onPick(hits[i]!);
    else onManual(term);
    setQ("");
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!rowCount) return;
      setOpen(true);
      setActive((a) => (a + (e.key === "ArrowDown" ? 1 : rowCount - 1)) % rowCount);
    } else if (e.key === "Enter") {
      if (!open || !rowCount) return;
      e.preventDefault();
      choose(active);
    } else if (e.key === "Escape") {
      if (open) {
        e.stopPropagation();
        setOpen(false);
      }
    }
  };

  const searchable = mirror?.ready !== false;

  return (
    <div ref={boxRef} className="relative">
      <label className="t-label mb-1 block" htmlFor={`${listId}-input`}>
        Ticker or company
      </label>
      <input
        id={`${listId}-input`}
        role="combobox"
        aria-expanded={open && rowCount > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && rowCount ? `${listId}-${active}` : undefined}
        autoComplete="off"
        // Autofocus is the point: the form opens because a position is being added, and this is
        // the field every add starts in.
        autoFocus={autoFocus}
        className="t-ui w-full rounded-md border border-line bg-surface px-2.5 py-1.5 focus:border-accent focus:outline-none"
        placeholder={
          searchable ? "6920 · レーザーテック · rezateku · lasertec" : "6920 (mirror not synced)"
        }
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />

      {open && rowCount > 0 && (
        <ul
          id={listId}
          ref={listRef}
          role="listbox"
          className="absolute z-20 mt-1 max-h-[19rem] w-full overflow-y-auto rounded-lg border border-line bg-surface py-1 shadow-lg"
        >
          {hits.map((h, i) => (
            <li
              key={h.code}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseEnter={() => setActive(i)}
              // mousedown, not click: click fires after blur has already closed the list.
              onMouseDown={(e) => {
                e.preventDefault();
                choose(i);
              }}
              className={`cursor-pointer px-2.5 py-1.5 ${i === active ? "bg-accent-soft" : ""}`}
            >
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-mono text-[13px] font-medium text-ink">{h.code}</span>
                <span className="text-[15px] text-ink">{h.nameJa}</span>
                {h.nameEn && <span className="t-meta">{h.nameEn}</span>}
                {taken.has(h.code) && (
                  <span className="rounded bg-field px-1.5 py-px text-[10px] font-semibold tracking-wide text-muted uppercase">
                    on list
                  </span>
                )}
              </div>
              <div className="t-meta">
                {h.market}
                {h.sector ? ` · ${h.sector}` : ""}
                {h.scale ? ` · ${h.scale}` : ""}
              </div>
            </li>
          ))}
          {manualRow && (
            <li
              id={`${listId}-${hits.length}`}
              role="option"
              aria-selected={active === hits.length}
              onMouseEnter={() => setActive(hits.length)}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(hits.length);
              }}
              className={`cursor-pointer border-t border-line-soft px-2.5 py-1.5 ${
                active === hits.length ? "bg-accent-soft" : ""
              }`}
            >
              <span className="t-ui text-ink-soft">
                Enter <span className="font-mono">{term}</span> by hand
              </span>
              <div className="t-meta">
                {loading
                  ? "searching…"
                  : hits.length === 0
                    ? "no listing matched — fill the fields yourself"
                    : "not one of these"}
              </div>
            </li>
          )}
        </ul>
      )}

      <p className="t-meta mt-1">
        {mirror === null
          ? " "
          : mirror.ready
            ? `${mirror.total.toLocaleString()} TSE listings · JPX ${fmtAsof(mirror.asof)}` +
              (mirror.withEnglish
                ? ` · ${mirror.withEnglish.toLocaleString()} with English names`
                : "")
            : "Ticker mirror is empty — run scripts/tickers.py --sync to search by name."}
      </p>
    </div>
  );
}

/** JPX stamps its file 20260731; nobody reads that as a date at a glance. */
function fmtAsof(asof: string | null): string {
  if (!asof || !/^\d{8}$/.test(asof)) return asof ?? "—";
  return `${asof.slice(0, 4)}-${asof.slice(4, 6)}-${asof.slice(6)}`;
}
