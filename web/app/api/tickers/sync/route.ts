import { NextResponse } from "next/server";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { listSyncs, mirrorStatus } from "@/lib/tickers";

const exec = promisify(execFile);

export const dynamic = "force-dynamic";

/** The systemd instance the button starts. `%i` becomes ticker_syncs.trigger, so the history
 *  distinguishes a button press from the Monday timer without a second unit file. */
const UNIT = "daily-feeds-tickers@manual.service";

/** GET — mirror state plus recent run history, for the dashboard's mirror panel. */
export async function GET() {
  return NextResponse.json({ mirror: mirrorStatus(), runs: listSyncs(12) });
}

/** POST — ask systemd to run the refresh now.
 *
 *  Starting the *unit* rather than spawning the script directly keeps one execution path for the
 *  schedule and the button: same command, same log, same recorded history, and systemd owns
 *  concurrency. `--no-block` is essential — a Type=oneshot start otherwise waits for the whole
 *  run (~2 min with the name fill), and the request would time out while the work succeeded.
 *
 *  No request data reaches the command line; the unit name is a constant.
 */
export async function POST() {
  const uid = process.getuid?.() ?? 1001;
  try {
    await exec("systemctl", ["--user", "start", "--no-block", UNIT], {
      // A systemd *service* inherits neither of these, and without them `systemctl --user`
      // cannot find the user manager's bus — it fails with "Failed to connect to bus".
      env: {
        ...process.env,
        XDG_RUNTIME_DIR: process.env.XDG_RUNTIME_DIR ?? `/run/user/${uid}`,
        DBUS_SESSION_BUS_ADDRESS:
          process.env.DBUS_SESSION_BUS_ADDRESS ?? `unix:path=/run/user/${uid}/bus`,
      },
      // --no-block returns as soon as the job is enqueued, so this is a guard against a wedged
      // bus, not against the run itself.
      timeout: 10_000,
    });
  } catch (e) {
    const err = e as { stderr?: string; message?: string };
    return NextResponse.json(
      { error: `could not start ${UNIT}: ${err.stderr?.trim() || err.message || "unknown"}` },
      { status: 500 }
    );
  }
  // 202: systemd has the job queued, the run itself outlives this request. The client polls GET.
  return NextResponse.json({ started: true, runs: listSyncs(12) }, { status: 202 });
}
