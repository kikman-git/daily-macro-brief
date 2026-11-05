import Link from "next/link";
import { getBrief } from "@/lib/feeds";
import { MarketStrip, Meta } from "./ui/atoms";
import { AudioPlayer } from "./ui/AudioPlayer";
import { AutoRefresh } from "./ui/AutoRefresh";
import { EventCard } from "./ui/EventCard";
import { Disclaimer, Header, Shell } from "./ui/Chrome";

export const dynamic = "force-dynamic";

const STATUS: Record<string, { label: string; cls: string }> = {
  pending: { label: "collecting", cls: "bg-field text-muted" },
  triaged: { label: "dives in flight", cls: "bg-accent-soft text-accent-deep" },
  published: { label: "complete", cls: "bg-on-soft text-on" },
  error: { label: "failed", cls: "bg-off-soft text-off" },
};

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date } = await searchParams;
  const brief = getBrief(date ?? null);

  if (!brief) {
    return (
      <Shell>
        <Header current="brief" />
        <div className="rounded-xl border border-dashed border-line bg-surface p-8 text-center">
          <p className="font-serif text-lg text-ink">No brief on file yet.</p>
          <p className="t-ui mt-2 text-muted">
            Run <code className="rounded bg-field px-1.5 py-0.5 font-mono text-[13px]">python3 scripts/run.py</code>{" "}
            to build one, or wait for the 21:10 UTC timer.
          </p>
        </div>
      </Shell>
    );
  }

  const deep = brief.events.filter((e) => e.tier === "deep");
  const thin = brief.events.filter((e) => e.tier === "thin");
  const st = STATUS[brief.status] ?? STATUS.pending;
  const stale = brief.feedHealth.filter((f) => f.status && !f.status.startsWith("ok"));
  // Only the live brief should poll; an archived date is finished by definition.
  const inFlight =
    !date &&
    (brief.status === "pending" ||
      brief.status === "triaged" ||
      brief.events.some((e) => e.dive?.status === "researching"));

  return (
    <Shell>
      <Header current="brief" />

      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <h2 className="font-serif text-xl text-ink">{brief.dateJst}</h2>
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-semibold tracking-wide uppercase ${st.cls}`}
          >
            {st.label}
          </span>
          <AutoRefresh active={inFlight} />
        </div>
        {brief.dates.length > 1 && (
          <form className="flex items-center gap-2">
            <label htmlFor="date" className="t-label">
              archive
            </label>
            <select
              id="date"
              name="date"
              defaultValue={brief.dateJst}
              className="t-ui rounded-md border border-line bg-surface px-2 py-1"
            >
              {brief.dates.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <button className="t-ui rounded-md border border-line px-2 py-1 text-muted hover:bg-wash">
              go
            </button>
          </form>
        )}
      </div>

      {/* An auth or stage failure must be impossible to mistake for a quiet news day. */}
      {brief.error && (
        <div className="mb-6 rounded-xl border border-off bg-off-soft p-4">
          <p className="t-ui-lg font-semibold text-off">This brief did not complete.</p>
          <pre className="mt-2 overflow-x-auto font-mono text-xs whitespace-pre-wrap text-ink-soft">
            {brief.error}
          </pre>
          <p className="t-meta mt-2">
            If this mentions auth, the claude-cli OAuth token needs refreshing — it lives about
            8 hours and the 21:10 UTC run depends on unattended rotation.
          </p>
        </div>
      )}

      {/* Above the reading surface on purpose: at 06:50 the useful question is "can I listen to
          this while I get to the desk", and that decision should not require scrolling. */}
      {brief.rollup && (
        <section className="mb-6">
          <AudioPlayer track={brief.rollup} variant="feature" />
        </section>
      )}

      {brief.regimeNote && (
        <section className="mb-6 rounded-xl border border-line bg-surface p-5">
          <p className="t-label mb-2">The tape you are walking into</p>
          <p className="prose-lede">{brief.regimeNote}</p>
        </section>
      )}

      <section className="mb-8">
        <MarketStrip rows={brief.market} />
      </section>

      {deep.length > 0 ? (
        <section className="mb-8 space-y-5">
          <h3 className="t-label">Deep dives · {deep.length}</h3>
          {deep.map((e) => (
            <EventCard key={e.id} ev={e} />
          ))}
        </section>
      ) : (
        brief.status !== "pending" && (
          <section className="mb-8 rounded-xl border border-dashed border-line bg-surface p-6">
            <p className="prose-lede text-ink">Nothing cleared the relevance floor today.</p>
            <p className="t-ui mt-2 max-w-[70ch] leading-relaxed text-muted">
              No event scored high enough on risk-on/risk-off potential to justify a deep dive.
              That is a real answer, not a gap — a quiet tape is worth knowing about, and
              manufacturing significance is how daily briefs go bad. The tail below is still the
              full day.
            </p>
          </section>
        )
      )}

      {thin.length > 0 && (
        <section className="space-y-2">
          <h3 className="t-label">Also on the tape · {thin.length}</h3>
          {thin.map((e) => (
            <EventCard key={e.id} ev={e} />
          ))}
        </section>
      )}

      <footer className="mt-8 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-4">
        <Meta>
          {brief.itemCount.toLocaleString()} items archived · {brief.feedHealth.length} feeds live
        </Meta>
        {stale.length > 0 && (
          <span className="t-meta text-off">
            {stale.length} feed{stale.length > 1 ? "s" : ""} failing:{" "}
            {stale.map((f) => f.name).join(", ")}
          </span>
        )}
        <Link href="/watchlist" className="t-meta">
          edit watchlist →
        </Link>
      </footer>
      <Disclaimer />
    </Shell>
  );
}
