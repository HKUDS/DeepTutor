"use client";

import type { CatalogProfile, ServiceName } from "./SettingsContext";

export const fieldControlClass =
  "w-full rounded-lg border border-[var(--border)] px-3 py-2 text-[14px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)]";

export const inputClass = `${fieldControlClass} bg-transparent placeholder:text-[var(--muted-foreground)]/40`;

export const nativeSelectClass = `${fieldControlClass} bg-[var(--background)] cursor-pointer disabled:cursor-not-allowed disabled:opacity-60`;

export const selectClass = `${nativeSelectClass} appearance-none`;

export const selectOptionClass =
  "bg-[var(--background)] text-[var(--foreground)]";

export const supportedSearchProviders = [
  "brave",
  "tavily",
  "jina",
  "searxng",
  "duckduckgo",
  "perplexity",
] as const;

export const deprecatedSearchProviders = new Set([
  "exa",
  "serper",
  "baidu",
  "openrouter",
]);

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

export function formatContextWindowSource(
  source: string | undefined,
  t: (key: string) => string,
): string {
  if (source === "manual") return t("Manual");
  if (source === "metadata") return t("Auto");
  if (source === "known_model") return t("Known");
  if (source === "default") return t("Default");
  return t("Unset");
}

export function formatContextWindowUpdatedAt(
  value: string | undefined,
  language: "en" | "zh",
): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(language === "zh" ? "zh-CN" : "en-US", {
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
  language: "en" | "zh",
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
    <div className="flex items-start justify-between gap-6 border-t border-[var(--border)]/50 px-1 py-4 first:border-t-0">
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
      <div className="shrink-0">{control}</div>
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
    <section className="mb-10">
      <header className="mb-3">
        <h2 className="text-[15px] font-semibold tracking-tight text-[var(--foreground)]">
          {title}
        </h2>
        {description && (
          <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {description}
          </p>
        )}
      </header>
      <div className="rounded-xl border border-[var(--border)]/60 bg-[var(--card)]/40 px-5">
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
}: {
  title: string;
  description?: string;
}) {
  return (
    <header className="mb-8">
      <h1 className="font-serif text-[22px] font-semibold tracking-tight text-[var(--foreground)]">
        {title}
      </h1>
      {description && (
        <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {description}
        </p>
      )}
    </header>
  );
}
