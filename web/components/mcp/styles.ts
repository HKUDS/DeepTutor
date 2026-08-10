// Field styling for the MCP editor. Deliberately local rather than reused from
// components/settings/shared: those controls are a size larger (14px), and this
// dense two-column editor was tuned at 13px.

export const inputClass =
  "w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)]/40 focus:border-[var(--ring)]";

export const selectClass =
  "w-full appearance-none rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--ring)]";

export const labelClass =
  "mb-1.5 block text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[var(--muted-foreground)]/80";

/** Neutral metadata pill (category, tier, transport) used across the store. */
export const chipClass =
  "inline-flex items-center rounded-full border border-[var(--border)]/60 bg-[var(--muted)]/40 px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]";
