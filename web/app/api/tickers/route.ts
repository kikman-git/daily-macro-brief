import { NextResponse } from "next/server";
import { searchTickers } from "@/lib/tickers";

export const dynamic = "force-dynamic";

/** GET /api/tickers?q=6920 — ranked matches from the JPX mirror.
 *
 *  No `q` answers the mirror's own state (row count, JPX snapshot date, English coverage), which
 *  is what the picker shows as its footer and how it decides whether to offer search at all.
 */
export async function GET(req: Request) {
  const url = new URL(req.url);
  const q = url.searchParams.get("q") ?? "";
  const limitRaw = Number(url.searchParams.get("limit"));
  const limit = Number.isFinite(limitRaw) ? Math.min(Math.max(limitRaw, 1), 50) : 12;
  // Long queries can only be paste accidents; folding one is cheap but scanning 4,400 rows with
  // it is not, and the answer is empty either way.
  if (q.length > 80) {
    return NextResponse.json({ hits: [], total: 0, asof: null, withEnglish: 0, ready: true });
  }
  return NextResponse.json(searchTickers(q, limit));
}
