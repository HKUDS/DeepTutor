"use client";

/**
 * Provider-grouped whitelist editor: one tri-state row per MCP server that
 * expands to the server's individual tools. With ~40 curated services × 10+
 * tools each, assigning a whole service has to be one click while fine-grained
 * control stays reachable.
 *
 * Shared by the partner tool picker and the admin grant editor: the grouping and
 * tri-state behaviour are identical in both, only the per-tool row styling
 * differs, so rows stay caller-rendered via `renderTool`. Deliberately free of
 * copy (checkbox + provider id + count + chevron) — the admin surface is not
 * wired to react-i18next, so any string here would end up duplicated or
 * untranslated.
 */

import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import {
  groupProviderTools,
  groupCounts,
  selectionFromCounts,
  setGroupSelected,
  toggleToolName,
  type ProviderToolLike,
} from "@/lib/mcp-tool-groups";

export default function McpToolGroups<T extends ProviderToolLike>({
  tools,
  selected,
  onChange,
  disabled = false,
  rowsClassName,
  renderTool,
}: {
  tools: readonly T[];
  /** Flat tool-name whitelist — exactly what the caller saves. */
  selected: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
  /** Container class for an expanded group's rows (callers keep their layout). */
  rowsClassName?: string;
  renderTool: (args: {
    tool: T;
    checked: boolean;
    onToggle: () => void;
  }) => ReactNode;
}) {
  // Expansion overrides keyed by provider id; a group with no override follows
  // its selection state, so a partially granted service opens on its own
  // (including after the options arrive asynchronously).
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});

  return (
    <div className="space-y-1.5">
      {groupProviderTools(tools).map((group) => {
        const counts = groupCounts(group.tools, selected);
        const state = selectionFromCounts(counts);
        const chosen = counts.hits;
        const open = overrides[group.id] ?? state === "partial";
        return (
          <div key={group.id}>
            <div className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-[var(--muted)]/50">
              <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={state === "all"}
                  disabled={disabled}
                  ref={(el) => {
                    if (el) el.indeterminate = state === "partial";
                  }}
                  onChange={() => {
                    // Pin the current expansion first: without an override the
                    // row follows `state === "partial"`, so ticking a partial
                    // group would flip it to "all" and snap it shut under the
                    // cursor mid-review.
                    setOverrides((current) => ({
                      ...current,
                      [group.id]: open,
                    }));
                    onChange(
                      setGroupSelected(selected, group.tools, state !== "all"),
                    );
                  }}
                />
                <span className="truncate font-mono text-[11.5px] text-[var(--foreground)]">
                  {group.id}
                </span>
              </label>
              <span className="shrink-0 text-[11px] tabular-nums text-[var(--muted-foreground)]">
                {chosen}/{group.tools.length}
              </span>
              <button
                type="button"
                aria-label={group.id}
                aria-expanded={open}
                onClick={() =>
                  setOverrides((current) => ({ ...current, [group.id]: !open }))
                }
                className="shrink-0 rounded p-0.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              >
                <ChevronRight
                  className={`h-3.5 w-3.5 transition-transform ${
                    open ? "rotate-90" : ""
                  }`}
                />
              </button>
            </div>
            {open && (
              <div className={`pl-4 ${rowsClassName ?? "space-y-1.5"}`}>
                {group.tools.map((tool) =>
                  renderTool({
                    tool,
                    checked: selected.includes(tool.name),
                    onToggle: () =>
                      onChange(toggleToolName(selected, tool.name)),
                  }),
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
