/**
 * Grouping and tri-state selection math for provider-supplied tools — MCP
 * servers today, CLI apps later (the backend tags every row with `kind`).
 *
 * A whitelist is stored as a FLAT list of tool names, both in a partner config
 * and in a user grant. The grouping here is purely presentational: every helper
 * takes flat names and returns flat names, so no caller has to reshape what it
 * saves. Kept React-free so the partner tool picker, the admin grant editor and
 * the node tests can all share it.
 */

/** The shared shape of an MCP option row from `build_tool_options`. */
export interface ProviderToolLike {
  name: string;
  /** Grouping key; `server` is the pre-provider spelling of the same value. */
  provider_id?: string;
  server?: string;
  /** `"mcp"` today; a `"cli"` kind arrives with the CLI-app providers. */
  kind?: string;
}

export interface ProviderToolGroup<T extends ProviderToolLike> {
  id: string;
  kind: string;
  tools: T[];
}

/** How much of a group is selected — drives the tri-state checkbox. */
export type GroupSelection = "all" | "none" | "partial";

/** Bucket for rows whose provider the backend could not name. */
const UNGROUPED_ID = "other";

export function providerGroupId(tool: ProviderToolLike): string {
  return tool.provider_id || tool.server || UNGROUPED_ID;
}

/** Group rows by provider, preserving the order the backend sent them in. */
export function groupProviderTools<T extends ProviderToolLike>(
  tools: readonly T[],
): ProviderToolGroup<T>[] {
  const groups: ProviderToolGroup<T>[] = [];
  const byId = new Map<string, ProviderToolGroup<T>>();
  for (const tool of tools) {
    const id = providerGroupId(tool);
    let group = byId.get(id);
    if (!group) {
      group = { id, kind: tool.kind || "mcp", tools: [] };
      byId.set(id, group);
      groups.push(group);
    }
    group.tools.push(tool);
  }
  return groups;
}

/** How many of a group's tools are selected, and how many there are. */
export function groupCounts(
  tools: readonly ProviderToolLike[],
  selected: readonly string[],
): { hits: number; total: number } {
  const picked = new Set(selected);
  return {
    hits: tools.reduce(
      (total, tool) => (picked.has(tool.name) ? total + 1 : total),
      0,
    ),
    total: tools.length,
  };
}

export function groupSelection(
  tools: readonly ProviderToolLike[],
  selected: readonly string[],
): GroupSelection {
  // Derived from the same pass as the "n of m" label — a caller that computed
  // the tri-state here and then re-scanned with `includes` per tool would be
  // quadratic across a catalog-sized server list.
  const { hits, total } = groupCounts(tools, selected);
  if (total === 0 || hits === 0) return "none";
  return hits === total ? "all" : "partial";
}

export function selectionFromCounts(counts: {
  hits: number;
  total: number;
}): GroupSelection {
  if (counts.total === 0 || counts.hits === 0) return "none";
  return counts.hits === counts.total ? "all" : "partial";
}

/**
 * Select or clear a whole group, returning the flat list to save. Names outside
 * the group are untouched; a re-selected group is rebuilt from the option rows,
 * which also drops duplicates a hand-edited config may carry.
 */
export function setGroupSelected(
  selected: readonly string[],
  tools: readonly ProviderToolLike[],
  next: boolean,
): string[] {
  const names = new Set(tools.map((tool) => tool.name));
  const others = selected.filter((name) => !names.has(name));
  return next ? [...others, ...tools.map((tool) => tool.name)] : others;
}

/** Flip one tool name in a flat whitelist. */
export function toggleToolName(
  selected: readonly string[],
  name: string,
): string[] {
  return selected.includes(name)
    ? selected.filter((item) => item !== name)
    : [...selected, name];
}
