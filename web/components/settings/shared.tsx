"use client";

import type {
  CatalogProfile,
  ServiceName,
} from "@/features/settings/store/SettingsStore";
import { localeForLanguage, type AppLanguage } from "@/i18n/languages";

// Tailwind 3 silently drops `<color>-[var(--token)]/NN`: our tokens are hex
// literals, so it cannot split them into channels and emits no rule at all.
// Every tint, hover and ring here therefore goes through color-mix, which does
// compile. See reference: the old `focus:border` alone gave these controls no
// hover affordance and no visible focus ring.
//
// `leading-5` is load-bearing rather than decoration. Without it a control
// inherits its line height from whatever wraps it, so the same class rendered
// 34px tall inside a `text-xs` label and 39px tall next to one — two fields of
// the same kind, side by side in one grid row, at different heights and with
// their tops out of line. Height now follows the class rather than the parent.
// `block` is there for the same reason from the other side: an inline-block
// control sits on a line box, so the parent's strut left a few pixels above it
// that a control in a differently-worded column did not have.
export const fieldControlClass =
  "block w-full rounded-lg border border-[var(--border)] px-3 py-2 text-[14px] leading-5 text-[var(--foreground)] outline-none transition-[border-color,box-shadow,background-color] duration-150 hover:border-[color-mix(in_srgb,var(--foreground)_22%,var(--border))] focus:border-[var(--ring)] focus:ring-2 focus:ring-[color-mix(in_srgb,var(--ring)_16%,transparent)] disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-[var(--border)]";

export const inputClass = `${fieldControlClass} bg-transparent placeholder:text-[color-mix(in_srgb,var(--muted-foreground)_55%,transparent)]`;

export const nativeSelectClass = `${fieldControlClass} bg-[var(--background)] cursor-pointer`;

// `appearance-none` strips the platform arrow, so `dt-select` paints one back.
export const selectClass = `${nativeSelectClass} dt-select appearance-none`;

export const selectOptionClass =
  "bg-[var(--background)] text-[var(--foreground)]";

// Nested panel inside a settings editor (provider probe, connection test, add
// form). These used to be `bg-[var(--muted)]/20`, which Tailwind 3 compiles to
// nothing at all for a hex custom property — so the panels had no fill and the
// pages read as a stack of hairlines. color-mix does compile.
export const subPanelClass =
  "rounded-xl border border-[color-mix(in_srgb,var(--border)_85%,transparent)] bg-[color-mix(in_srgb,var(--muted)_40%,transparent)]";

export function stringifyExtraHeaders(
  value: CatalogProfile["extra_headers"],
): string {
  if (!value) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return "";
  }
}

export function statusDotClass(configured: boolean, hasError: boolean): string {
  if (hasError) return "bg-red-400";
  if (configured) return "bg-emerald-500";
  return "bg-[var(--border)]";
}

/**
 * Hairline between two items of the settings status strip. Lives here rather
 * than inside the strip because items that can render nothing (MemoryUsageItem)
 * have to draw their own leading rule — otherwise hiding the item leaves a
 * dangling separator behind.
 */
export function StatusStripDivider() {
  return (
    <span
      aria-hidden
      className="hidden h-7 w-px shrink-0 bg-[color-mix(in_srgb,var(--border)_70%,transparent)] sm:block"
    />
  );
}

export function formatContextWindowSource(
  source: string | undefined,
  t: (key: string) => string,
): string {
  if (source === "manual") return t("Manual");
  if (source === "metadata") return t("Provider metadata");
  if (source === "known_model") return t("Model catalog (models.dev)");
  if (source === "default") return t("Conservative fallback (not detected)");
  return t("Unset");
}

export function formatContextWindowUpdatedAt(
  value: string | undefined,
  language: AppLanguage,
): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(localeForLanguage(language), {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function activeProfileDetail(
  profile: CatalogProfile | null,
  service: ServiceName,
  t: (key: string) => string,
): string {
  if (!profile) return t("No profile");
  if (service === "search") return profile.provider || t("No provider");
  return profile.base_url || t("No endpoint");
}

export function activeModelDetail(
  profile: CatalogProfile | null,
  model: { model?: string; name?: string } | null,
  service: ServiceName,
  t: (key: string) => string,
): string {
  if (service === "search") return profile?.provider || t("No provider");
  return model?.model || model?.name || t("No model selected");
}

// Category-label typography. English looks good with uppercase + wide tracking;
// CJK glyphs are already square blocks so we drop both and bump size a hair.
export function labelClass(
  size: "sm" | "md" | "lg",
  language: AppLanguage,
): string {
  if (language === "zh") {
    if (size === "sm") return "text-[10.5px] font-medium";
    if (size === "lg") return "text-[12px] font-medium";
    return "text-[11px] font-medium";
  }
  if (size === "sm")
    return "text-[9.5px] font-semibold uppercase tracking-[0.16em]";
  if (size === "lg") return "text-[11px] uppercase tracking-[0.16em]";
  return "text-[10px] font-semibold uppercase tracking-[0.16em]";
}

// One-row settings group used on simple pages (Appearance, Status etc.).
// Title + optional description on the left, control flushed right. Matches
// the visual rhythm used on Codex-style preferences pages.
export function SettingRow({
  title,
  description,
  control,
}: {
  title: string;
  description?: string;
  control: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:gap-6 border-t border-[color-mix(in_srgb,var(--border)_50%,transparent)] py-3.5 first:border-t-0">
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-medium text-[var(--foreground)]">
          {title}
        </div>
        {description && (
          <p className="mt-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {description}
          </p>
        )}
      </div>
      <div className="max-w-full shrink-0">{control}</div>
    </div>
  );
}

// Page-level section group. Title + optional description, then children.
export function SettingSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-8">
      <header className="mb-2">
        <h2 className="text-[15px] font-semibold tracking-tight text-[var(--foreground)]">
          {title}
        </h2>
        {description && (
          <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {description}
          </p>
        )}
      </header>
      {/* A rule, not a box. The app divides with hairlines and whitespace —
          a bordered, tinted panel around rows that already separate
          themselves with hairlines was dividing the same content twice. The
          top rule is what tells a section where it starts, and it has to live
          here rather than on the first row because sections also hold custom
          content (theme tiles, previews) that draws no rule of its own. */}
      <div className="border-t border-[color-mix(in_srgb,var(--border)_60%,transparent)]">
        {children}
      </div>
    </section>
  );
}

// Page heading shared across settings sub-pages. The global Save Draft / Apply
// toolbar (which also shows where this module persists to) lives above this, so
// each page just owns its title row.
export function SettingsPageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  // The page's primary action belongs on the title row. Workspace pages used to
  // repeat a second description line just to have somewhere to hang the button,
  // which left a dead band between the heading and the content.
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-7 flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1
          data-tour="tour-page-heading"
          className="text-[26px] font-semibold tracking-tight text-[var(--foreground)]"
        >
          {title}
        </h1>
        {description && (
          <p className="mt-1.5 max-w-[62ch] text-[13px] leading-relaxed text-[var(--muted-foreground)]">
            {description}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      )}
    </header>
  );
}
