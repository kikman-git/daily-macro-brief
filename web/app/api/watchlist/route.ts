import { NextResponse } from "next/server";
import { getSettings, listWatchlist, saveSettings, upsertWatch } from "@/lib/feeds";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ rows: listWatchlist(), settings: getSettings() });
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  if (!body || typeof body !== "object") {
    return NextResponse.json({ error: "invalid body" }, { status: 400 });
  }
  try {
    if (body.settings) {
      saveSettings(body.settings);
      return NextResponse.json({ settings: getSettings() });
    }
    const row = upsertWatch(body, body.id ? Number(body.id) : undefined);
    return NextResponse.json({ row });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 400 });
  }
}
