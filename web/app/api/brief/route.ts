import { NextResponse } from "next/server";
import { getBrief } from "@/lib/feeds";

export const dynamic = "force-dynamic";

/** Also the deploy health check — see package.json `deploy`. */
export async function GET(req: Request) {
  const date = new URL(req.url).searchParams.get("date");
  const brief = getBrief(date);
  return brief
    ? NextResponse.json(brief)
    : NextResponse.json({ error: "no brief", date }, { status: 404 });
}
