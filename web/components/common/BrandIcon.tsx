"use client";

import { useTranslation } from "react-i18next";

import {
  brandIconFor,
  brandInitials,
  type BrandNamespace,
} from "@/lib/brand-icons";

/**
 * The square mark in front of a store entry: the product's own logo when we have
 * it, an initials monogram when we do not.
 *
 * Rendered inline from a bundled CC0 path — no image request, so opening the
 * store does not tell a vendor that this person is looking at their service.
 *
 * Monochrome (`currentColor`) rather than the brand's own hex, for two reasons:
 * a dozen brand colours in one grid reads as noise next to DeepTutor's own
 * restrained palette, and several brand hexes fail contrast against one of the
 * two themes. The hex is kept in the generated data if an accent is ever wanted.
 */
export default function BrandIcon({
  namespace,
  id,
  name,
  size = "sm",
  className = "",
}: {
  namespace: BrandNamespace;
  /** Catalog entry id — what the slug tables are keyed on. */
  id: string;
  /** Display name, used for the monogram and the accessible label. */
  name: string;
  size?: "sm" | "lg";
  className?: string;
}) {
  const icon = brandIconFor(namespace, id);
  const box =
    size === "lg" ? "h-11 w-11 text-[14px]" : "mt-0.5 h-7 w-7 text-[10.5px]";
  const glyph = size === "lg" ? 20 : 14;

  return (
    <span
      // The name is already adjacent in every current caller, so the mark is
      // decorative and announcing it again would just double every row.
      aria-hidden
      title={icon ? icon.title : name}
      className={`flex shrink-0 items-center justify-center rounded-lg border border-[var(--border)]/60 bg-[var(--background)] font-semibold tracking-tight text-[var(--muted-foreground)] ${box} ${className}`}
    >
      {icon ? (
        <svg
          viewBox="0 0 24 24"
          width={glyph}
          height={glyph}
          fill="currentColor"
          role="presentation"
        >
          <path d={icon.path} />
        </svg>
      ) : (
        brandInitials(name)
      )}
    </span>
  );
}

/**
 * The attribution these marks require.
 *
 * Simple Icons ships the *paths* under CC0, which is why they can be bundled —
 * but each mark is still its owner's trademark. Shown once per store rather than
 * per row: it is a legal notice, not a caption.
 */
export function TrademarkNote({ className = "" }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <p
      className={`text-[11px] leading-relaxed text-[var(--muted-foreground)]/70 ${className}`}
    >
      {t(
        "Product names and logos are trademarks of their respective owners, shown for identification only.",
      )}
    </p>
  );
}

/**
 * The bare mark, with no box — for a row that already has its own leading glyph
 * and a settled rhythm. Returns `null` when there is no logo, so the caller keeps
 * whatever generic icon it had rather than being handed a monogram that would not
 * fit the slot.
 */
export function BrandGlyph({
  namespace,
  id,
  size = 14,
  className = "",
}: {
  namespace: BrandNamespace;
  id: string;
  size?: number;
  className?: string;
}) {
  const icon = brandIconFor(namespace, id);
  if (!icon) return null;
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
      role="presentation"
      aria-hidden
      className={className}
    >
      <title>{icon.title}</title>
      <path d={icon.path} />
    </svg>
  );
}
