import Link from "next/link";
import { ReaderControls } from "./ReaderControls";

export function Header({ current }: { current: "brief" | "watchlist" }) {
  const tab = (href: string, key: string, label: string) => (
    <Link
      key={key}
      href={href}
      className={`t-ui rounded-md px-2.5 py-1 font-medium ${
        current === key ? "bg-ink text-cream" : "text-muted hover:bg-wash"
      }`}
    >
      {label}
    </Link>
  );
  return (
    <header className="mb-7 flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-b border-line pb-4">
      <div>
        <h1 className="font-serif text-2xl leading-none text-ink">Macro Brief</h1>
        <p className="t-label mt-1.5">07:00 JST pre-open · Japanese equities</p>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <nav className="flex items-center gap-1">
          {tab("/", "brief", "Brief")}
          {tab("/watchlist", "watchlist", "Watchlist")}
        </nav>
        <ReaderControls />
      </div>
    </header>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto max-w-[52rem] px-5 py-8">{children}</main>;
}

/** The system judges events; the trader judges positions. Stated on every page on purpose. */
export function Disclaimer() {
  return (
    <p className="t-meta mt-10 max-w-[70ch] border-t border-line pt-4 leading-relaxed">
      This brief judges whether <em>events</em> are risk-on or risk-off catalysts. It does not
      make position recommendations, and it never sizes or times a trade — those calls are
      yours. Market figures are computed from the free Yahoo chart endpoint before the model
      runs; any number in a dive that is not from that snapshot carries its own citation.
    </p>
  );
}
