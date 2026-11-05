"use client";

import { useEffect, useState } from "react";

type Theme = "paper" | "dark";
type Size = "s" | "m" | "l";

const SIZES: { key: Size; px: string; label: string }[] = [
  { key: "s", px: "0.6875rem", label: "Small text" },
  { key: "m", px: "0.8125rem", label: "Medium text" },
  { key: "l", px: "0.9375rem", label: "Large text" },
];

const group = "flex items-center gap-px rounded-md border border-line bg-surface p-px";
const btn = "rounded-[5px] px-1.5 py-1 leading-none transition-colors";

export function ReaderControls() {
  // Server renders the documented default; the inline head script has already applied the real
  // stored values to <html> before paint, and this effect syncs the button state to whatever is
  // actually on screen. Doing it the other way round would flash the wrong theme.
  const [theme, setTheme] = useState<Theme>("paper");
  const [size, setSize] = useState<Size>("m");

  useEffect(() => {
    const d = document.documentElement;
    setTheme(d.dataset.theme === "dark" ? "dark" : "paper");
    const z = d.dataset.size;
    setSize(z === "s" || z === "l" ? z : "m");
  }, []);

  const pick = (next: Partial<{ theme: Theme; size: Size }>) => {
    const d = document.documentElement;
    try {
      if (next.theme) {
        d.dataset.theme = next.theme;
        localStorage.setItem("df-theme", next.theme);
        setTheme(next.theme);
      }
      if (next.size) {
        d.dataset.size = next.size;
        localStorage.setItem("df-size", next.size);
        setSize(next.size);
      }
    } catch {
      // Private mode or a blocked origin: the attribute still changed, so the setting works for
      // this visit and simply does not persist. Not worth surfacing.
    }
  };

  return (
    <div className="flex items-center gap-2">
      <div className={group} role="group" aria-label="Colour theme">
        <button
          type="button"
          onClick={() => pick({ theme: "paper" })}
          aria-pressed={theme === "paper"}
          title="Paper"
          className={`${btn} ${theme === "paper" ? "bg-ink text-cream" : "text-muted hover:bg-wash"}`}
        >
          <Sun />
        </button>
        <button
          type="button"
          onClick={() => pick({ theme: "dark" })}
          aria-pressed={theme === "dark"}
          title="Dark"
          className={`${btn} ${theme === "dark" ? "bg-ink text-cream" : "text-muted hover:bg-wash"}`}
        >
          <Moon />
        </button>
      </div>

      <div className={group} role="group" aria-label="Text size">
        {SIZES.map((s) => (
          <button
            key={s.key}
            type="button"
            onClick={() => pick({ size: s.key })}
            aria-pressed={size === s.key}
            title={s.label}
            style={{ fontSize: s.px }}
            className={`${btn} font-serif font-semibold ${
              size === s.key ? "bg-ink text-cream" : "text-muted hover:bg-wash"
            }`}
          >
            A
          </button>
        ))}
      </div>
    </div>
  );
}

/* Inline SVG rather than emoji: ☀/☾ render at wildly different sizes across platforms and one
   of the two is usually colour, which fights the button's own foreground. */
const ico = {
  width: 14,
  height: 14,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

const Sun = () => (
  <svg {...ico}>
    <circle cx="12" cy="12" r="4.2" />
    <path d="M12 2.6v2.2M12 19.2v2.2M2.6 12h2.2M19.2 12h2.2M5.4 5.4l1.6 1.6M17 17l1.6 1.6M18.6 5.4L17 7M7 17l-1.6 1.6" />
  </svg>
);

const Moon = () => (
  <svg {...ico}>
    <path d="M20.5 14.4A8.6 8.6 0 1 1 9.6 3.5a6.9 6.9 0 0 0 10.9 10.9z" />
  </svg>
);
