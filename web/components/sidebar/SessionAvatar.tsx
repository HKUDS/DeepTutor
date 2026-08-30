"use client";

import { createElement } from "react";
import {
  Cherry,
  Cloud,
  Compass,
  Cookie,
  Droplet,
  Feather,
  Flame,
  Heart,
  Leaf,
  Lightbulb,
  Moon,
  Music,
  Sparkles,
  Sprout,
  Star,
  Sun,
  type LucideIcon,
} from "lucide-react";

/**
 * A curated set of minimalist, friendly icons, each paired with its own
 * muted accent color. Each idle session is mapped deterministically to one
 * of these so the sidebar feels varied and alive without ever shuffling on
 * re-render. Colors are hand-picked at a shared, low-key saturation/
 * lightness so the row reads as a coherent set rather than a bright,
 * clashing rainbow. Running sessions reuse the same icon but switch to the
 * "active" blue and add a gentle wiggle (see `.dt-session-icon-running` in
 * globals.css).
 */
const ICONS: { icon: LucideIcon; color: string }[] = [
  { icon: Sparkles, color: "#8b6fd9" },
  { icon: Sprout, color: "#79b366" },
  { icon: Leaf, color: "#4f9e82" },
  { icon: Feather, color: "#5fa8a3" },
  { icon: Cloud, color: "#7096c4" },
  { icon: Droplet, color: "#5580c9" },
  { icon: Sun, color: "#d1863f" },
  { icon: Moon, color: "#7b74c9" },
  { icon: Flame, color: "#cf6a55" },
  { icon: Star, color: "#c7a03d" },
  { icon: Heart, color: "#cf6f96" },
  { icon: Lightbulb, color: "#cbb23f" },
  { icon: Compass, color: "#4a9bb0" },
  { icon: Cherry, color: "#c15a72" },
  { icon: Cookie, color: "#b9803f" },
  { icon: Music, color: "#a468b0" },
];

const RUNNING_COLOR = "#3b82f6";

// Cheap, stable hash so a given session_id always maps to the same icon.
function hashString(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function pickSessionIconEntry(sessionId: string): {
  icon: LucideIcon;
  color: string;
} {
  if (!sessionId) return ICONS[0];
  return ICONS[hashString(sessionId) % ICONS.length];
}

export function pickSessionIcon(sessionId: string): LucideIcon {
  return pickSessionIconEntry(sessionId).icon;
}

interface SessionAvatarProps {
  sessionId: string;
  running?: boolean;
  size?: number;
  className?: string;
}

export function SessionAvatar({
  sessionId,
  running = false,
  size = 12,
  className,
}: SessionAvatarProps) {
  const entry = pickSessionIconEntry(sessionId);
  // createElement avoids the static-components lint rule that mis-flags
  // <Icon /> when Icon is a lookup into ICONS (stable per session_id).
  // `color` is set explicitly (not via a `text-*` className) so each
  // session keeps its own hue regardless of the caller's text color.
  return createElement(entry.icon, {
    size,
    strokeWidth: 1.5,
    color: running ? RUNNING_COLOR : entry.color,
    className: `shrink-0 ${running ? "dt-session-icon-running" : ""} ${
      className ?? ""
    }`,
  });
}
