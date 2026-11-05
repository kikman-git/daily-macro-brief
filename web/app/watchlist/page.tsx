import { getSettings, listWatchlist } from "@/lib/feeds";
import { Header, Shell } from "../ui/Chrome";
import { WatchlistEditor } from "./WatchlistEditor";

export const dynamic = "force-dynamic";

export default async function WatchlistPage() {
  const rows = listWatchlist();
  const { bookStyle, sectors } = getSettings();

  return (
    <Shell>
      <Header current="watchlist" />
      <div className="mb-6">
        <h2 className="font-serif text-xl text-ink">Watchlist</h2>
        <p className="t-ui mt-1.5 max-w-[70ch] leading-relaxed text-muted">
          The universe every dive reasons about. Each dive receives this list and closes with a{" "}
          <strong className="font-semibold text-ink-soft">Watchlist impact</strong> section, so
          the more accurate the drivers, the more specific the transmission.
        </p>
        <p className="t-meta mt-2 rounded-lg border border-line bg-wash px-3 py-2">
          Book: <span className="text-ink-soft">long {bookStyle.long}</span>, hedged{" "}
          <span className="text-ink-soft">{bookStyle.hedge}</span>
        </p>
      </div>
      <WatchlistEditor initialRows={rows} initialSectors={sectors} />
    </Shell>
  );
}
