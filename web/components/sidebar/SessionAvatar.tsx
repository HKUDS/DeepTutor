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
 * A curated set of minimalist, friendly icons. Each idle session is mapped
 * deterministically to one of these so the sidebar feels varied without ever
 * shuffling on re-render. Running sessions reuse the same assignment but add
 * a gentle wiggle animation (see `.dt-session-icon-running` in globals.css).
 */
const ICONS: LucideIcon[] = [
  Sparkles,
  Sprout,
  Leaf,
  Feather,
  Cloud,
  Droplet,
  Sun,
  Moon,
  Flame,
  Star,
  Heart,
  Lightbulb,
  Compass,
  Cherry,
  Cookie,
  Music,
];

// Cheap, stable hash so a given session_id always maps to the same icon.
function hashString(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function pickSessionIcon(sessionId: string): LucideIcon {
  if (!sessionId) return ICONS[0];
  return ICONS[hashString(sessionId) % ICONS.length];
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
  size = 14,
  className,
}: SessionAvatarProps) {
  // createElement avoids the static-components lint rule that mis-flags
  // <Icon /> when Icon is a lookup into ICONS (stable per session_id).
  return createElement(pickSessionIcon(sessionId), {
    size,
    strokeWidth: 1.6,
    className: `shrink-0 ${running ? "dt-session-icon-running" : ""} ${
      className ?? ""
    }`,
  });
}
