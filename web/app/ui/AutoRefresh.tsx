"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/* Incremental publish only pays off if the page actually updates. Dives land minutes apart
 * while the brief is being read at 07:00, so refresh on a timer for as long as any dive is
 * still in flight — and stop once nothing is pending, so a finished brief is a static page. */
export function AutoRefresh({ active, seconds = 30 }: { active: boolean; seconds?: number }) {
  const router = useRouter();
  const [ticks, setTicks] = useState(0);

  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => {
      setTicks((t) => t + 1);
      router.refresh();
    }, seconds * 1000);
    return () => clearInterval(id);
  }, [active, seconds, router]);

  if (!active) return null;
  return (
    <span className="t-meta inline-flex items-center gap-1.5">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
      auto-refreshing every {seconds}s{ticks > 0 && ` · ${ticks} check${ticks > 1 ? "s" : ""}`}
    </span>
  );
}
