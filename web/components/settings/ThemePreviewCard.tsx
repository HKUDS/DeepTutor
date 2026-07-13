"use client";

import { Check } from "lucide-react";

import type { UiSettings } from "./SettingsContext";

type Theme = UiSettings["theme"];

// Explicit palette values lifted from app/globals.css — kept here as plain
// hex/rgba so each preview tile can render its theme's colours even while
// the actual document theme is something else. Keep in sync with globals.css
// when colours change there.
type Palette = {
  bg: string;
  fg: string;
  card: string;
  primary: string;
  muted: string;
  border: string;
  // True for translucent themes — adds a soft gradient/backdrop to convey
  // the "frosted glass" treatment visually.
  glass?: boolean;
};

const PALETTES: Record<Theme, Palette> = {
  // theme id "light" applies no class → :root Cream palette (warm parchment,
  // the default; renamed from generic "Light" to honestly signal its warmth)
  light: {
    bg: "#fdfcf9",
    fg: "#1c1816",
    card: "#ffffff",
    primary: "#b0501e",
    muted: "#f1ede2",
    border: "#e6decc",
  },
  // theme id "snow" applies the .theme-snow class → "Default": pure-white
  // neutral palette, grey surfaces, blue primary (Codex-style chrome)
  snow: {
    bg: "#ffffff",
    fg: "#0d0d0d",
    card: "#ffffff",
    primary: "#2563eb",
    muted: "#f2f2f2",
    border: "#e5e5e5",
  },
  dark: {
    bg: "#1a1918",
    fg: "#e8e4de",
    card: "#242220",
    primary: "#d4734b",
    muted: "#2a2725",
    border: "#3a3634",
  },
  glass: {
    bg: "#0e0d1a",
    fg: "#ffffff",
    card: "rgba(255,255,255,0.06)",
    primary: "#a855f7",
    muted: "rgba(255,255,255,0.06)",
    border: "rgba(255,255,255,0.12)",
    glass: true,
  },
};

// Renders a miniature DeepTutor UI mockup in the given theme's palette —
// a left sidebar with one highlighted nav row, a content area with two
// text lines and an accent button. Pure SVG so it stays crisp at any
// device pixel ratio without leaking real interactive controls.
function MiniPreview({ palette }: { palette: Palette }) {
  const { bg, fg, card, primary, muted, border, glass } = palette;
  return (
    <svg viewBox="0 0 160 96" className="block h-full w-full" aria-hidden>
      {/* Outer frame */}
      <rect x="0" y="0" width="160" height="96" rx="6" fill={bg} />
      {glass && (
        <>
          <defs>
            <radialGradient id="glass-shine" cx="20%" cy="0%" r="80%">
              <stop offset="0%" stopColor="rgba(168,85,247,0.38)" />
              <stop offset="100%" stopColor="rgba(168,85,247,0)" />
            </radialGradient>
          </defs>
          <rect
            x="0"
            y="0"
            width="160"
            height="96"
            rx="6"
            fill="url(#glass-shine)"
          />
        </>
      )}

      {/* Sidebar */}
      <rect x="0" y="0" width="44" height="96" fill={muted} />
      {/* Sidebar nav rows */}
      <rect
        x="8"
        y="14"
        width="28"
        height="3"
        rx="1.5"
        fill={fg}
        opacity="0.45"
      />
      <rect x="6" y="26" width="32" height="10" rx="3" fill={card} />
      <rect
        x="10"
        y="30"
        width="20"
        height="2.5"
        rx="1.25"
        fill={fg}
        opacity="0.9"
      />
      <circle cx="40" cy="31" r="1.5" fill={primary} />
      <rect
        x="8"
        y="44"
        width="24"
        height="2.5"
        rx="1.25"
        fill={fg}
        opacity="0.45"
      />
      <rect
        x="8"
        y="54"
        width="26"
        height="2.5"
        rx="1.25"
        fill={fg}
        opacity="0.45"
      />
      <rect
        x="8"
        y="64"
        width="22"
        height="2.5"
        rx="1.25"
        fill={fg}
        opacity="0.45"
      />

      {/* Sidebar divider */}
      <line x1="44" y1="0" x2="44" y2="96" stroke={border} strokeWidth="0.5" />

      {/* Content card */}
      <rect
        x="54"
        y="14"
        width="96"
        height="68"
        rx="4"
        fill={card}
        stroke={border}
        strokeWidth="0.5"
      />
      {/* Title line */}
      <rect
        x="62"
        y="22"
        width="40"
        height="3.5"
        rx="1.5"
        fill={fg}
        opacity="0.85"
      />
      {/* Body lines */}
      <rect
        x="62"
        y="34"
        width="78"
        height="2.5"
        rx="1.25"
        fill={fg}
        opacity="0.35"
      />
      <rect
        x="62"
        y="42"
        width="64"
        height="2.5"
        rx="1.25"
        fill={fg}
        opacity="0.35"
      />
      <rect
        x="62"
        y="50"
        width="72"
        height="2.5"
        rx="1.25"
        fill={fg}
        opacity="0.35"
      />
      {/* Accent button */}
      <rect x="62" y="64" width="22" height="9" rx="2.5" fill={primary} />
    </svg>
  );
}

export function ThemePreviewCard({
  theme,
  label,
  selected,
  onSelect,
}: {
  theme: Theme;
  label: string;
  selected: boolean;
  onSelect: (theme: Theme) => void;
}) {
  const palette = PALETTES[theme];
  return (
    <button
      type="button"
      onClick={() => onSelect(theme)}
      aria-pressed={selected}
      className={`group relative flex flex-col items-stretch gap-2 rounded-xl border p-1.5 text-left transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${
        selected
          ? "border-[var(--foreground)] bg-[var(--card)] shadow-sm"
          : "border-[var(--border)]/60 bg-transparent hover:border-[var(--border)] hover:bg-[var(--muted)]/25"
      }`}
    >
      <div
        className="relative overflow-hidden rounded-lg ring-1"
        style={{
          aspectRatio: "5 / 3",
          boxShadow: `inset 0 0 0 1px ${palette.border}`,
        }}
      >
        <MiniPreview palette={palette} />
        {selected && (
          <div className="absolute right-1.5 top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--foreground)] text-[var(--background)]">
            <Check className="h-2.5 w-2.5" strokeWidth={3} />
          </div>
        )}
      </div>
      <div className="flex items-center justify-between px-1 pb-0.5">
        <span
          className={`text-[12.5px] tracking-tight ${
            selected
              ? "font-medium text-[var(--foreground)]"
              : "text-[var(--muted-foreground)] group-hover:text-[var(--foreground)]"
          }`}
        >
          {label}
        </span>
        <div className="flex -space-x-1">
          {[palette.primary, palette.fg, palette.muted].map((c, i) => (
            <span
              key={i}
              className="h-2.5 w-2.5 rounded-full ring-1 ring-[var(--background)]"
              style={{ background: c }}
            />
          ))}
        </div>
      </div>
    </button>
  );
}
