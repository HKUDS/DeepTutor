"use client";

import { createElement, useState } from "react";
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
  Shield,
  Sparkles,
  Sprout,
  Star,
  Sun,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  AVATAR_COLOR_NAMES,
  AVATAR_COLORS,
  AVATAR_ICON_NAMES,
  fallbackAvatarFor,
  parseAvatarMarker,
} from "@/lib/avatar";
import { avatarImageUrl } from "@/lib/profile-api";

/**
 * User avatars. Marker parsing and the deterministic fallback live in
 * lib/avatar.ts (pure, unit-tested); this component maps icon names to
 * lucide components and renders the marker.
 *
 * Admins get an amber ring at every size plus a small shield badge once the
 * avatar is large enough for it to stay legible (>= 40px).
 */

// Must cover every name in AVATAR_ICON_NAMES (lib/avatar.ts).
export const AVATAR_ICONS: Record<string, LucideIcon> = {
  sparkles: Sparkles,
  sprout: Sprout,
  leaf: Leaf,
  feather: Feather,
  cloud: Cloud,
  droplet: Droplet,
  sun: Sun,
  moon: Moon,
  flame: Flame,
  star: Star,
  heart: Heart,
  lightbulb: Lightbulb,
  compass: Compass,
  cherry: Cherry,
  cookie: Cookie,
  music: Music,
};

// Re-exported so picker UIs only need one import site.
export {
  AVATAR_COLOR_NAMES,
  AVATAR_COLORS,
  AVATAR_ICON_NAMES,
  fallbackAvatarFor,
};

const ADMIN_RING_COLOR = "#e0a83c";

interface UserAvatarProps {
  username: string;
  /** Needed to resolve "img:" markers to an image URL. */
  userId?: string;
  /** Avatar marker; empty/undefined renders the deterministic fallback. */
  avatar?: string;
  /** Admins get the amber ring (and a shield badge at size >= 40). */
  role?: string;
  size?: number;
  className?: string;
}

export function UserAvatar({
  username,
  userId,
  avatar = "",
  role,
  size = 28,
  className,
}: UserAvatarProps) {
  const { t } = useTranslation();
  const [imageBroken, setImageBroken] = useState(false);
  // A re-upload changes the marker version; give the new URL a fresh chance.
  // Render-time reset (instead of an effect) per react.dev's "adjusting
  // state when a prop changes" guidance.
  const imageKey = `${userId ?? ""}:${avatar}`;
  const [lastImageKey, setLastImageKey] = useState(imageKey);
  if (imageKey !== lastImageKey) {
    setLastImageKey(imageKey);
    setImageBroken(false);
  }

  const isAdmin = role === "admin";
  const showBadge = isAdmin && size >= 40;
  const descriptor = parseAvatarMarker(avatar);
  const isImage =
    descriptor.kind === "image" && Boolean(userId) && !imageBroken;

  // A stored marker can name an icon/color this build doesn't know (an older
  // client, or a hand-set marker). Validate against the known sets and fall
  // back to the deterministic avatar so it never renders blank
  // (AVATAR_COLORS[unknown] would be undefined -> an invisible avatar).
  const fallback = fallbackAvatarFor(username);
  let iconName: string;
  let colorName: string;
  if (descriptor.kind === "icon") {
    iconName =
      descriptor.icon in AVATAR_ICONS ? descriptor.icon : fallback.icon;
    colorName =
      descriptor.color in AVATAR_COLORS ? descriptor.color : fallback.color;
  } else {
    iconName = fallback.icon;
    colorName = fallback.color;
  }

  const ringStyle = isAdmin
    ? {
        outline: `${Math.max(1.5, size / 18)}px solid ${ADMIN_RING_COLOR}`,
        outlineOffset: `${Math.max(1, size / 28)}px`,
      }
    : undefined;
  const adminLabel = t("Administrator");

  return (
    <span
      className={`relative inline-flex shrink-0 ${className ?? ""}`}
      style={{ width: size, height: size }}
      title={isAdmin ? `${username} — ${adminLabel}` : username}
      aria-label={isAdmin ? `${username} (${adminLabel})` : username}
    >
      {isImage ? (
        /* Dynamic backend URL with cookie auth; next/image cannot optimize it. */
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={avatarImageUrl(userId as string, avatar)}
          alt=""
          width={size}
          height={size}
          onError={() => setImageBroken(true)}
          className="h-full w-full rounded-full object-cover"
          style={ringStyle}
        />
      ) : (
        <span
          className="flex h-full w-full items-center justify-center rounded-full text-white"
          style={{ backgroundColor: AVATAR_COLORS[colorName], ...ringStyle }}
        >
          {createElement(AVATAR_ICONS[iconName] ?? Sparkles, {
            size: Math.round(size * 0.55),
            strokeWidth: 1.8,
          })}
        </span>
      )}
      {showBadge && (
        <span
          className="absolute flex items-center justify-center rounded-full"
          style={{
            right: -size / 14,
            bottom: -size / 14,
            width: Math.round(size * 0.38),
            height: Math.round(size * 0.38),
            backgroundColor: "#f7ecd4",
            border: "2px solid var(--background)",
            color: "#8a5d0b",
          }}
          aria-hidden
        >
          <Shield size={Math.round(size * 0.2)} strokeWidth={2.2} />
        </span>
      )}
    </span>
  );
}
