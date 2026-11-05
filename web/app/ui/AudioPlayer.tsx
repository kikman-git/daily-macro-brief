"use client";

import { useEffect, useRef, useState } from "react";
import type { AudioTrack } from "@/lib/types";

const SPEEDS = [1, 1.25, 1.5, 1.75];
/* Two players on one page must never talk over each other, and the roll-up contains the same
 * words as the dive tracks — so starting one broadcasts, and every other player stands down. */
const CHANNEL = "df-audio-play";

const clock = (s: number) => {
  if (!Number.isFinite(s) || s < 0) return "0:00";
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s - m * 60)).padStart(2, "0")}`;
};

export function AudioPlayer({
  track,
  variant = "inline",
  title,
}: {
  track: AudioTrack | null;
  variant?: "inline" | "feature";
  title?: string;
}) {
  const ref = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [at, setAt] = useState(0);
  // The DB already knows the duration, so the total renders correctly before the browser has
  // fetched a single byte of metadata.
  const [total, setTotal] = useState(track?.durationS ?? 0);
  const [rate, setRate] = useState(1);

  useEffect(() => {
    try {
      const r = Number(localStorage.getItem("df-rate"));
      if (SPEEDS.includes(r)) setRate(r);
    } catch {
      /* not persisting playback speed is not worth a visible error */
    }
  }, []);

  useEffect(() => {
    if (ref.current) ref.current.playbackRate = rate;
  }, [rate, playing]);

  useEffect(() => {
    const stand_down = (e: Event) => {
      if ((e as CustomEvent).detail !== track?.id) ref.current?.pause();
    };
    addEventListener(CHANNEL, stand_down);
    return () => removeEventListener(CHANNEL, stand_down);
  }, [track?.id]);

  if (!track) return null;

  if (track.status !== "done") {
    // Audio is an enhancement, so a failure is a quiet line rather than an alarm — but it is
    // still shown, because a silently missing player looks identical to a feature that does
    // not exist.
    return (
      <p className="t-meta">
        {track.status === "pending"
          ? "Audio is being rendered."
          : `Audio unavailable — ${track.error ?? "synthesis failed"}`}
      </p>
    );
  }

  const src = `/api/audio/${track.id}`;
  const feature = variant === "feature";

  const toggle = () => {
    const a = ref.current;
    if (!a) return;
    if (a.paused) {
      dispatchEvent(new CustomEvent(CHANNEL, { detail: track.id }));
      a.playbackRate = rate;
      void a.play();
    } else {
      a.pause();
    }
  };

  const nudge = (d: number) => {
    const a = ref.current;
    if (a) a.currentTime = Math.min(Math.max(0, a.currentTime + d), a.duration || total);
  };

  const cycle = () => {
    const next = SPEEDS[(SPEEDS.indexOf(rate) + 1) % SPEEDS.length];
    setRate(next);
    try {
      localStorage.setItem("df-rate", String(next));
    } catch {
      /* see above */
    }
  };

  const pill =
    "rounded-md border border-line px-2 py-1 t-meta text-muted hover:bg-wash disabled:opacity-40";

  return (
    <div
      className={
        feature
          ? "rounded-xl border border-line bg-surface p-4"
          : "rounded-lg border border-line bg-wash p-3"
      }
    >
      {feature && (
        <div className="mb-2.5 flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <p className="t-label">{title ?? "Listen to the morning"}</p>
          <span className="t-meta">
            {clock(total)} · read aloud, roll-up of every dive
          </span>
        </div>
      )}
      <div className="flex items-center gap-2.5">
        <button
          onClick={toggle}
          aria-label={playing ? "Pause" : "Play"}
          className={`flex shrink-0 items-center justify-center rounded-full bg-ink text-cream ${
            feature ? "h-10 w-10" : "h-8 w-8"
          }`}
        >
          {playing ? <Pause /> : <Play />}
        </button>

        <button onClick={() => nudge(-15)} className={pill} title="Back 15 seconds">
          −15s
        </button>
        <button onClick={() => nudge(30)} className={pill} title="Forward 30 seconds">
          +30s
        </button>

        <input
          type="range"
          min={0}
          max={total || 1}
          step={1}
          value={Math.min(at, total || 1)}
          onChange={(e) => {
            const v = Number(e.target.value);
            setAt(v);
            if (ref.current) ref.current.currentTime = v;
          }}
          aria-label="Seek"
          className="h-1 min-w-16 flex-1 cursor-pointer appearance-none rounded-full bg-line [accent-color:var(--color-accent)]"
        />

        <span className="t-meta shrink-0 font-mono tabular-nums">
          {clock(at)} / {clock(total)}
        </span>

        <button onClick={cycle} className={`${pill} shrink-0 font-mono`} title="Playback speed">
          {rate}×
        </button>
      </div>

      <audio
        ref={ref}
        src={src}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => setAt(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          const d = e.currentTarget.duration;
          if (Number.isFinite(d) && d > 0) setTotal(d);
        }}
        onEnded={() => {
          setPlaying(false);
          setAt(0);
        }}
      />
    </div>
  );
}

const Play = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
    <path d="M7 4.5v15l13-7.5z" />
  </svg>
);

const Pause = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
    <path d="M6.5 4.5h4v15h-4zM13.5 4.5h4v15h-4z" />
  </svg>
);
