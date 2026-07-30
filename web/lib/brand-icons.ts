/**
 * Resolving a catalog entry to a brand mark.
 *
 * Two namespaces, kept apart: an MCP server id and a CLI app id can collide
 * (`exa` is both a hosted search MCP and an installed CLI), and they are not the
 * same product. Callers say which store they are rendering.
 *
 * Everything here is a pure lookup over the generated tables, so the store pages
 * stay free of icon logic and this stays testable.
 */

import {
  BRAND_ICONS,
  CLI_ICON_SLUGS,
  MCP_ICON_SLUGS,
  type BrandIcon,
} from "@/lib/brand-icons.generated";

export type BrandNamespace = "mcp" | "cli";

/**
 * The mark for *id* in *namespace*, or `null` when there is none.
 *
 * `null` is the common case and not a failure: coverage is partial on purpose
 * (see `brand-slugs.ts`), and a monogram is the designed fallback rather than a
 * degraded one.
 */
export function brandIconFor(namespace: BrandNamespace, id: string): BrandIcon | null {
  const table = namespace === "mcp" ? MCP_ICON_SLUGS : CLI_ICON_SLUGS;
  for (const key of candidateKeys(id)) {
    const slug = table[key];
    if (slug) return BRAND_ICONS[slug] ?? null;
  }
  return null;
}

/**
 * The keys to try for *id*, exact form first.
 *
 * Exact-first matters: several catalog ids genuinely end in `-cli`
 * (`1password-cli`, `android-cli`, `minimax-cli`), and a normaliser that always
 * stripped that suffix would look up `1password` and find nothing. The looser
 * forms exist only for a *renamed* install — the MCP store lets the installer
 * choose a local name, and the common edits are case and separator changes.
 */
function candidateKeys(id: string): string[] {
  const raw = String(id ?? "").trim();
  if (!raw) return [];
  const lowered = raw.toLowerCase();
  const dashed = lowered.replace(/[\s_.]+/g, "-");
  const stripped = dashed.replace(/^cli-/, "").replace(/-cli$/, "");
  return [...new Set([raw, lowered, dashed, stripped])];
}

/**
 * Up to two initials for the monogram fallback.
 *
 * Word-aware: "Google Maps" → "GM", "firecrawl" → "FI". Falls back to the first
 * two characters so a single CJK word still renders something.
 */
export function brandInitials(name: string): string {
  const cleaned = String(name ?? "").trim();
  if (!cleaned) return "?";
  const words = cleaned.split(/[\s\-_./]+/).filter(Boolean);
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return cleaned.slice(0, 2).toUpperCase();
}

export type { BrandIcon };
