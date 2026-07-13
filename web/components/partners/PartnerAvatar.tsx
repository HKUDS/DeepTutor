"use client";

/**
 * Round partner avatar. Precedence: uploaded image (data URL) → emoji on a
 * colored disc → name initial on a colored disc. Emoji and background color
 * compose (iOS-contacts style) instead of being mutually exclusive.
 */

export const PARTNER_COLORS = [
  "#b0501e", // ember (primary-adjacent)
  "#8c6a2f", // ochre
  "#4f7a5b", // moss
  "#3d6b8a", // lake
  "#6d5a8c", // plum
  "#8a4f5f", // rose
  "#a8763e", // amber
  "#5b8a8a", // teal
] as const;

export default function PartnerAvatar({
  name,
  emoji,
  color,
  image,
  size = 40,
  className = "",
}: {
  name: string;
  emoji?: string;
  color?: string;
  /** Custom avatar as a data URL — wins over emoji/color when set. */
  image?: string;
  size?: number;
  className?: string;
}) {
  if (image) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={image}
        alt=""
        aria-hidden
        className={`shrink-0 select-none rounded-full object-cover ${className}`}
        style={{ width: size, height: size }}
      />
    );
  }

  const initial = (name || "?").trim().charAt(0).toUpperCase();
  // Emoji discs default to a soft neutral so an un-colored emoji keeps the
  // familiar look; a chosen color becomes the disc behind the emoji.
  const background = color || (emoji ? "var(--muted)" : PARTNER_COLORS[0]);
  return (
    <span
      aria-hidden
      className={`flex shrink-0 select-none items-center justify-center rounded-full text-white ${className}`}
      style={{
        width: size,
        height: size,
        background,
        fontSize: emoji ? size * 0.55 : size * 0.42,
        fontWeight: 600,
      }}
    >
      {emoji || initial}
    </span>
  );
}
