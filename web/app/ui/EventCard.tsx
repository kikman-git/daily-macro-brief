"use client";

import { useState } from "react";
import type { BriefEvent } from "@/lib/types";
import { Markdown } from "./markdown";
import { AudioPlayer } from "./AudioPlayer";
import { Meta, RiskPill } from "./atoms";

const jstTime = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleTimeString("en-GB", {
        timeZone: "Asia/Tokyo",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

function Elapsed({ from }: { from: string | null }) {
  if (!from) return null;
  const mins = Math.round((Date.now() - new Date(from).getTime()) / 60000);
  return <Meta>{mins < 1 ? "just started" : `${mins} min elapsed`}</Meta>;
}

function SourceList({ items }: { items: BriefEvent["items"] }) {
  if (!items.length) return null;
  return (
    <ul className="mt-3 space-y-1.5">
      {items.map((i) => (
        <li key={i.url} className="t-ui flex gap-2 leading-snug">
          <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-fainter" />
          <span>
            {/* Google News links are opaque redirect tokens, but they do resolve in a
                browser — so they stay clickable here while the dive text must cite the
                publisher's own URL. */}
            <a href={i.url} target="_blank" rel="noopener noreferrer" className="text-ink-soft">
              {i.title}
            </a>
            {i.source && <Meta> · {i.source}</Meta>}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Frontmatter the dive committed to, shown as a scannable header above the prose. */
function Verdict({ dive }: { dive: NonNullable<BriefEvent["dive"]> }) {
  const rows: [string, string | null][] = [
    ["confidence", dive.confidence],
    ["horizon", dive.horizon],
    ["JP equities", dive.jpEquityDirection],
  ];
  return (
    <div className="rounded-lg border border-line bg-wash p-4">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <RiskPill dir={dive.verdict} size="lg" />
        {rows.map(([k, v]) =>
          v ? (
            <span key={k} className="t-label">
              {k} <span className="ml-1 font-semibold text-ink-soft normal-case">{v}</span>
            </span>
          ) : null
        )}
      </div>
      {dive.highBetaNote && (
        <p className="prose-note mt-3 border-t border-line pt-3">
          <span className="t-label text-accent-deep">high-beta </span>
          {dive.highBetaNote}
        </p>
      )}
      {dive.falsifier && (
        <p className="prose-note mt-2 text-muted">
          <span className="t-label">falsifier </span>
          {dive.falsifier}
        </p>
      )}
    </div>
  );
}

export function EventCard({ ev }: { ev: BriefEvent }) {
  const deep = ev.tier === "deep";
  const [open, setOpen] = useState(deep);
  const dive = ev.dive;

  return (
    <article
      className={`rounded-xl border bg-surface ${
        deep ? "border-line shadow-[0_1px_2px_rgba(26,25,21,0.04)]" : "border-line-soft"
      }`}
    >
      <header className={`flex items-start gap-3 ${deep ? "p-5 pb-4" : "px-4 py-3"}`}>
        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <RiskPill dir={ev.riskDirection} score={ev.riskScore} />
            {ev.thread && (
              <span className="rounded bg-field px-1.5 py-0.5 font-mono text-[11px] text-muted">
                {ev.thread.slug}
              </span>
            )}
            {dive?.status === "researching" && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-semibold tracking-wide text-accent-deep uppercase">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                researching
              </span>
            )}
            {dive?.status === "error" && (
              <span className="rounded-full bg-off-soft px-2 py-0.5 text-[11px] font-semibold tracking-wide text-off uppercase">
                dive failed
              </span>
            )}
          </div>
          <h2
            className={`font-serif leading-snug text-ink ${deep ? "text-[22px]" : "text-[16px]"}`}
          >
            {ev.titleEn}
          </h2>
          {ev.titleJa && <p className="t-ui mt-1 leading-snug text-muted">{ev.titleJa}</p>}
          {ev.why && (
            <p className="prose-note mt-2">
              <span className="t-label">channel </span>
              {ev.why}
            </p>
          )}
        </div>
        <button
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="t-ui shrink-0 rounded-md border border-line px-2.5 py-1 text-muted hover:bg-wash"
        >
          {open ? "hide" : dive?.bodyMd ? "read" : "sources"}
        </button>
      </header>

      {open && (
        <div className={`border-t border-line-soft ${deep ? "p-5" : "px-4 py-3"}`}>
          {dive?.status === "researching" && (
            <div className="t-ui rounded-lg border border-dashed border-line bg-wash p-4 text-muted">
              Opus is researching this event now — up to 30 minutes. The page will show the
              analysis once it lands. <Elapsed from={dive.startedAt} />
            </div>
          )}
          {dive?.status === "error" && (
            <div className="rounded-lg border border-off-soft bg-off-soft p-4">
              <p className="t-ui font-semibold text-off">This dive failed to complete.</p>
              <pre className="mt-2 overflow-x-auto font-mono text-xs whitespace-pre-wrap text-ink-soft">
                {dive.error}
              </pre>
            </div>
          )}
          {dive?.status === "done" && dive.bodyMd && (
            <>
              <Verdict dive={dive} />
              {ev.audio && (
                <div className="mt-3">
                  <AudioPlayer track={ev.audio} />
                </div>
              )}
              <div className="prose-dive mt-6">
                <Markdown source={dive.bodyMd} />
              </div>
              <footer className="mt-6 border-t border-line pt-3">
                <Meta>
                  {dive.model} · {dive.sources.length} sources ·{" "}
                  {jstTime(dive.finishedAt) ?? "—"} JST
                </Meta>
                {/* A completed dive that broke the output contract is still worth reading, so
                    this is a note rather than an alarm — but it must be visible, because a
                    missing section looks like nothing at all on a rendered page. */}
                {dive.error && (
                  <p className="t-meta mt-1.5 leading-snug">
                    ⚠ {dive.error.replace(/^contract: /, "output contract: ")}
                  </p>
                )}
              </footer>
            </>
          )}
          <div className={dive?.status === "done" ? "mt-4 border-t border-line pt-3" : ""}>
            <p className="t-label">Clustered headlines ({ev.items.length})</p>
            <SourceList items={ev.items} />
          </div>
        </div>
      )}
    </article>
  );
}
