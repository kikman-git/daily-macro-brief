import { createReadStream, promises as fsp } from "node:fs";
import { Readable } from "node:stream";
import { audioFile } from "@/lib/feeds";

export const dynamic = "force-dynamic";

/* Range support is not optional for a six-minute track: without it Safari will not scrub, and
 * on iOS it refuses to start playback at all. */
const BASE = {
  "Content-Type": "audio/mp4",
  "Accept-Ranges": "bytes",
  "Cache-Control": "private, max-age=86400",
};

const stream = (file: string, opts?: { start: number; end: number }) =>
  Readable.toWeb(createReadStream(file, opts)) as ReadableStream;

export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const file = audioFile(Number((await ctx.params).id));
  if (!file) return new Response("not found", { status: 404 });

  let size: number;
  try {
    size = (await fsp.stat(file)).size;
  } catch {
    // The row says done but the file is gone — a moved or pruned audio dir, not a bug worth 500.
    return new Response("audio file missing", { status: 404 });
  }

  const header = req.headers.get("range");
  if (!header) {
    return new Response(stream(file), {
      headers: { ...BASE, "Content-Length": String(size) },
    });
  }

  const m = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  const unsatisfiable = () =>
    new Response(null, { status: 416, headers: { ...BASE, "Content-Range": `bytes */${size}` } });
  if (!m || (m[1] === "" && m[2] === "")) return unsatisfiable();

  // "bytes=-500" means the last 500 bytes, not "from 0 to 500".
  const suffix = m[1] === "";
  const start = suffix ? Math.max(0, size - Number(m[2])) : Number(m[1]);
  const end = suffix || m[2] === "" ? size - 1 : Math.min(Number(m[2]), size - 1);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end || start >= size) {
    return unsatisfiable();
  }

  return new Response(stream(file, { start, end }), {
    status: 206,
    headers: {
      ...BASE,
      "Content-Length": String(end - start + 1),
      "Content-Range": `bytes ${start}-${end}/${size}`,
    },
  });
}
