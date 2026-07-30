import {
  McpApiError,
  type McpCatalogEntry,
  type McpCatalogField,
  type McpCatalogPage,
} from "@/lib/mcp-api";

/**
 * Pure logic behind the per-user MCP store (`/space/mcp`).
 *
 * Everything here is deliberately free of React and of `fetch` so the rules that
 * decide what the page shows — which refusal message, which category chips,
 * whether Install is allowed, what "Load more" accumulates — are unit-testable
 * without a DOM.
 */

/**
 * Category order for the store's filter row.
 *
 * Mirrors the closed `CatalogCategory` enum in
 * `deeptutor/services/mcp/catalog/models.py`. It is only an ordering: the counts
 * decide which chips exist, so a category added on the backend still appears
 * (at the end) rather than vanishing from the filter.
 */
export const MCP_CATALOG_CATEGORIES: readonly string[] = [
  "search",
  "docs",
  "code",
  "data",
  "browser",
  "science",
  "maps",
  "business",
  "ai",
  "utility",
];

/** The tiers a store visitor can filter by, in menu order. */
export const MCP_CATALOG_TIERS: readonly string[] = ["curated", "registry"];

export interface McpCategoryChip {
  category: string;
  count: number;
}

/**
 * The category chips to render, in canonical order.
 *
 * Zero-count categories are dropped: the backend counts only the entries this
 * surface can install, so a chip with no matches would open onto an empty grid.
 */
export function catalogCategoryChips(
  counts: Record<string, number>,
): McpCategoryChip[] {
  const known = MCP_CATALOG_CATEGORIES.filter((category) => counts[category] > 0)
    .map((category) => ({ category, count: counts[category] }));
  const extra = Object.keys(counts)
    .filter(
      (category) =>
        counts[category] > 0 && !MCP_CATALOG_CATEGORIES.includes(category),
    )
    .sort()
    .map((category) => ({ category, count: counts[category] }));
  return [...known, ...extra];
}

// ── refusals ─────────────────────────────────────────────────────────────

/**
 * i18n key for a backend refusal code, or `null` when only the backend's own
 * message can explain the failure.
 *
 * The codes come from `deeptutor/api/routers/space_mcp.py`; their messages are
 * English strings assembled server-side, and several of them need an actionable
 * next step rather than a translation of the cause.
 */
export function mcpRefusalKey(code: string): string | null {
  return REFUSAL_KEYS[code] ?? null;
}

const REFUSAL_KEYS: Record<string, string> = {
  "mcp.stdio_not_allowed": "mcp.refusal.stdioNotAllowed",
  "mcp.blocked_url": "mcp.refusal.blockedUrl",
  "mcp.name_reserved": "mcp.refusal.nameReserved",
  "mcp.too_many_servers": "mcp.refusal.tooManyServers",
  "mcp.missing_credential": "mcp.refusal.missingCredential",
  "mcp.entry_admin_only": "mcp.refusal.entryAdminOnly",
};

/**
 * Codes whose backend message names the actual cause, so the translated
 * sentence is a preamble rather than a replacement. A blocked URL is the
 * clearest case: "unresolvable host", "only http/https", and "private address"
 * all arrive under one code and need different fixes from the reader.
 */
const REFUSALS_KEEPING_DETAIL = new Set(["mcp.blocked_url"]);

/**
 * Human-readable copy for a failed MCP request.
 *
 * A mapped refusal renders as the app's own sentence; anything else falls back
 * to the message the backend sent, which for a blocked URL or a transport error
 * carries the only detail worth reading.
 */
export function describeMcpError(
  error: unknown,
  t: (key: string) => string,
): string {
  if (error instanceof McpApiError && error.code) {
    const key = mcpRefusalKey(error.code);
    if (key) {
      const detail = REFUSALS_KEEPING_DETAIL.has(error.code)
        ? error.message.trim()
        : "";
      return detail ? `${t(key)} ${detail}` : t(key);
    }
  }
  return error instanceof Error ? error.message : String(error);
}

// ── credential form ──────────────────────────────────────────────────────

/**
 * Which required credentials are still blank.
 *
 * Whitespace counts as blank, matching the backend's `build_server_config`,
 * which strips before deciding a required field is missing — a form that
 * accepted " " would send a request the backend refuses.
 */
export function missingRequiredFields(
  fields: readonly McpCatalogField[],
  values: Record<string, string>,
): string[] {
  return fields
    .filter((field) => field.required && !(values[field.key] ?? "").trim())
    .map((field) => field.key);
}

/** Whether Install may be pressed for *fields* filled with *values*. */
export function canInstallEntry(
  fields: readonly McpCatalogField[],
  values: Record<string, string>,
): boolean {
  return missingRequiredFields(fields, values).length === 0;
}

/** Drop blank values so an optional field is left unset rather than cleared. */
export function filledCredentials(
  values: Record<string, string>,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(values).filter(([, value]) => value.trim() !== ""),
  );
}

// ── pagination ───────────────────────────────────────────────────────────

export interface McpCatalogList {
  entries: McpCatalogEntry[];
  /** Cursor for the next page; `""` once the store is exhausted. */
  cursor: string;
  total: number;
  categories: Record<string, number>;
}

/**
 * Fold one page into the list already on screen.
 *
 * Pass `null` for the first page of a fresh query. Entries are de-duplicated by
 * id so a re-fetched cursor (a double click on "Load more") cannot double a row,
 * and `total`/`categories` always come from the newest page — the backend
 * recomputes them per query.
 */
export function appendCatalogPage(
  previous: McpCatalogList | null,
  page: McpCatalogPage,
): McpCatalogList {
  const entries = previous ? [...previous.entries] : [];
  const seen = new Set(entries.map((entry) => entry.id));
  for (const entry of page.entries) {
    if (seen.has(entry.id)) continue;
    seen.add(entry.id);
    entries.push(entry);
  }
  return {
    entries,
    cursor: page.next_cursor,
    total: page.total,
    categories: page.categories,
  };
}

// ── presentation helpers ─────────────────────────────────────────────────

/**
 * Pick *lang* out of an i18n map, degrading to the base language then English.
 * Mirrors `localized_text` in the catalog models.
 */
export function localizedCatalogText(
  texts: Record<string, string>,
  lang: string,
): string {
  for (const key of [lang, lang.split("-")[0], "en"]) {
    const text = texts[key];
    if (text) return text;
  }
  return Object.values(texts).find((text) => text) ?? "";
}

/**
 * Initials for an entry's avatar. The catalog ships no logos on purpose — a
 * remote logo per installed service would leak the viewer's app list to each
 * vendor — so the store draws its own mark from the name.
 */
export function catalogInitials(displayName: string): string {
  const words = displayName.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}
