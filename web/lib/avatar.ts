/**
 * Pure avatar logic — marker parsing and the deterministic fallback.
 *
 * The marker format (persisted in the user record) is:
 *   ""                    — deterministic icon+color derived from the username
 *   "icon:<name>:<color>" — an explicitly picked icon and color (keys below)
 *   "img:<version>"       — an uploaded image served from /api/v1/auth/avatar
 *
 * Kept free of React/lucide imports so node unit tests can pin the behavior;
 * the UserAvatar component maps icon names to lucide components on top.
 */

// Same curated icon set as SessionAvatar, so the app keeps one visual voice.
// Order matters: the fallback hash indexes into this list, so reordering or
// removing entries silently reassigns every user's fallback avatar.
export const AVATAR_ICON_NAMES: readonly string[] = [
  "sparkles",
  "sprout",
  "leaf",
  "feather",
  "cloud",
  "droplet",
  "sun",
  "moon",
  "flame",
  "star",
  "heart",
  "lightbulb",
  "compass",
  "cherry",
  "cookie",
  "music",
];

// Fixed hexes (not theme variables) so a user's chosen color reads the same
// across Light/Dark/Snow/Glass themes; all carry white icons at 4.5:1+.
export const AVATAR_COLORS: Record<string, string> = {
  violet: "#7c5fd3",
  blue: "#3f7cc8",
  teal: "#2a9d8f",
  green: "#4f9d4f",
  amber: "#c98a2d",
  rose: "#d05c7c",
  slate: "#6b7a8c",
  pink: "#bb5fb2",
};

export const AVATAR_COLOR_NAMES = Object.keys(AVATAR_COLORS);

// Cheap, stable FNV-1a hash (same as SessionAvatar) so a username always maps
// to the same fallback icon/color without anything persisted.
function hashString(input: string): number {
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function fallbackAvatarFor(username: string): {
  icon: string;
  color: string;
} {
  const hash = hashString(username || "user");
  return {
    icon: AVATAR_ICON_NAMES[hash % AVATAR_ICON_NAMES.length],
    // ">>>" not ">>": a signed shift of a hash >= 2^31 yields a negative
    // index, which would silently drop the background color entirely.
    color: AVATAR_COLOR_NAMES[(hash >>> 4) % AVATAR_COLOR_NAMES.length],
  };
}

export type AvatarDescriptor =
  | { kind: "image"; version: string }
  | { kind: "icon"; icon: string; color: string }
  | { kind: "fallback" };

const ICON_MARKER_RE = /^icon:([a-z0-9-]+):([a-z0-9-]+)$/;

/**
 * Classify an avatar marker. Unknown icon/color names (e.g. from a stale or
 * hand-edited user record) degrade to the deterministic fallback instead of
 * rendering a broken avatar.
 */
export function parseAvatarMarker(
  marker: string | null | undefined,
): AvatarDescriptor {
  const value = (marker ?? "").trim();
  if (value.startsWith("img:")) {
    return { kind: "image", version: value.slice(4) };
  }
  const match = ICON_MARKER_RE.exec(value);
  if (
    match &&
    AVATAR_ICON_NAMES.includes(match[1]) &&
    AVATAR_COLORS[match[2]]
  ) {
    return { kind: "icon", icon: match[1], color: match[2] };
  }
  return { kind: "fallback" };
}
