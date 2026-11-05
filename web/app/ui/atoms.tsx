import type { MarketRow, RiskDirection } from "@/lib/types";

const RISK: Record<RiskDirection, { label: string; bg: string; fg: string }> = {
  "risk-on": { label: "risk-on", bg: "bg-on-soft", fg: "text-on" },
  "risk-off": { label: "risk-off", bg: "bg-off-soft", fg: "text-off" },
  ambiguous: { label: "ambiguous", bg: "bg-amb-soft", fg: "text-amb" },
};

export function RiskPill({
  dir,
  score,
  size = "sm",
}: {
  dir: RiskDirection | null;
  score?: number;
  size?: "sm" | "lg";
}) {
  const r = (dir && RISK[dir]) ?? { label: dir ?? "unscored", bg: "bg-field", fg: "text-muted" };
  const pad = size === "lg" ? "px-2.5 py-1 text-[13px]" : "px-2 py-0.5 text-[11px]";
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full font-semibold tracking-wide uppercase ${pad} ${r.bg} ${r.fg}`}
    >
      {r.label}
      {score != null && <span className="font-mono opacity-80">{score}</span>}
    </span>
  );
}

export function Meta({ children }: { children: React.ReactNode }) {
  return <span className="t-meta">{children}</span>;
}

/** Signed percent, coloured by direction. Never invents a value for null. */
export function Pct({ v, digits = 2 }: { v: number | null; digits?: number }) {
  if (v == null) return <span className="text-muted">—</span>;
  const c = v > 0 ? "text-on" : v < 0 ? "text-off" : "text-muted";
  return (
    <span className={`font-mono ${c}`}>
      {v > 0 ? "+" : ""}
      {v.toFixed(digits)}%
    </span>
  );
}

const SHORT: Record<string, string> = {
  "^N225": "Nikkei",
  "1305.T": "TOPIX",
  "2516.T": "Growth250",
  "JPY=X": "USD/JPY",
  "^VIX": "VIX",
  "^SOX": "SOX",
  "^GSPC": "S&P 500",
};

/** The computed snapshot. Every number in the brief traces back to this table. */
export function MarketStrip({ rows }: { rows: MarketRow[] }) {
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="t-ui w-full">
        <thead>
          <tr className="border-b border-line">
            <th className="t-label px-3 py-2 text-left">Instrument</th>
            <th className="t-label px-3 py-2 text-right">Last</th>
            <th className="t-label px-3 py-2 text-right">1d</th>
            <th className="t-label px-3 py-2 text-right">vs MA20</th>
            <th className="t-label px-3 py-2 text-right">vs MA50</th>
            <th className="t-label px-3 py-2 text-right">from 60d high</th>
            <th className="t-label px-3 py-2 text-right">rv20</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} className="border-b border-line-soft last:border-0">
              <td className="px-3 py-2 whitespace-nowrap">
                <span className="font-medium">{SHORT[r.symbol] ?? r.symbol}</span>
                {r.symbol === "2516.T" && (
                  <span className="ml-1.5 rounded bg-accent-soft px-1 py-px text-[10px] font-semibold tracking-wide text-accent-deep uppercase">
                    high-beta
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-right font-mono">
                {r.error ? <span className="t-meta text-off">{r.error}</span> : r.last?.toLocaleString()}
              </td>
              <td className="px-3 py-2 text-right"><Pct v={r.chgPct} /></td>
              <td className="px-3 py-2 text-right"><Pct v={r.vsMa20Pct} /></td>
              <td className="px-3 py-2 text-right"><Pct v={r.vsMa50Pct} /></td>
              <td className="px-3 py-2 text-right"><Pct v={r.drawdownPct} /></td>
              <td className="px-3 py-2 text-right font-mono text-muted">
                {r.realizedVolPct == null ? "—" : `${r.realizedVolPct.toFixed(1)}%`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
