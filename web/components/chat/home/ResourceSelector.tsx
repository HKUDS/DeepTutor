"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Plug, Search, Wand2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLingerExpand } from "@/hooks/use-linger-expand";
import { useOutsideClick } from "@/hooks/use-outside-click";
import type { WorkspaceResourceOption } from "@/lib/workspaces-api";

/**
 * Skill / MCP scope selector (composer rail).
 *
 * Both kinds are the same state as the KB scope — a SESSION-level narrowing of
 * what the conversation can reach, persisted in session.preferences and only
 * ever intersected with what the workspace already allows. So they share one
 * component and differ only in wording, icon, and the secondary line each row
 * has room for (a skill's description; an MCP server's origin and whether it is
 * currently switched off).
 *
 * An empty selection means "everything this workspace allows", which is why the
 * resting label is the plain kind name rather than a count of zero: nothing has
 * been narrowed, so nothing is being withheld.
 */
export default function ResourceSelector({
  kind,
  options,
  selected,
  onToggle,
  placement = "top",
  pinned = false,
  embedded = false,
}: {
  kind: "skills" | "mcp";
  options: WorkspaceResourceOption[];
  selected: string[];
  onToggle: (id: string) => void;
  placement?: "top" | "bottom";
  /** Keep the label visible instead of collapsing to the icon at rest. */
  pinned?: boolean;
  /** Render the picker contents inside a shared resource panel. */
  embedded?: boolean;
}) {
  const { t } = useTranslation();
  const [openState, setOpenState] = useState(false);
  const open = embedded || openState;
  const {
    expanded,
    linger,
    triggerProps: lingerProps,
  } = useLingerExpand(open, 1200, pinned);
  const setOpen = (next: boolean) => {
    setOpenState(next);
    if (!next) {
      // Reset the filter in the same event rather than in an effect on `open`:
      // a stale query only ever matters to a menu being reopened, and closing
      // is the one moment both facts are already in hand.
      setQuery("");
      // Keep the label out for a beat after close so a just-made change
      // registers before the chip collapses.
      linger();
    }
  };
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");

  useOutsideClick(rootRef, open, () => setOpen(false));

  // Only worth a search field once scanning the list is slower than typing.
  const searchable = embedded || options.length > 8;
  useEffect(() => {
    if (open && searchable) searchRef.current?.focus({ preventScroll: true });
  }, [open, searchable]);

  const Icon = kind === "skills" ? Wand2 : Plug;
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return options;
    return options.filter(
      (option) =>
        option.name.toLowerCase().includes(needle) ||
        (option.description ?? "").toLowerCase().includes(needle),
    );
  }, [options, query]);

  const count = selected.length;
  const label =
    count === 0
      ? kind === "skills"
        ? t("Skills")
        : t("MCP")
      : count === 1
        ? (options.find((option) => option.id === selected[0])?.name ??
          selected[0])
        : `${count} ${kind === "skills" ? t("skills") : t("mcp servers")}`;
  const menuPlacementClass =
    placement === "bottom" ? "top-full mt-1.5" : "bottom-full mb-1.5";

  return (
    <div ref={rootRef} className="relative">
      {!embedded && (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-label={
            kind === "skills" ? t("Select skills") : t("Select MCP servers")
          }
          aria-expanded={open}
          {...lingerProps}
          className={`inline-flex h-8 shrink-0 items-center rounded-lg px-2 text-[14px] font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] ${
            open
              ? "bg-[var(--muted)] text-[var(--foreground)]"
              : count > 0
                ? "text-[var(--primary)] hover:bg-[var(--primary)]/[0.07]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
          }`}
        >
          <Icon size={16} strokeWidth={1.7} className="shrink-0" />
          <span
            className={`flex min-w-0 items-center gap-1 overflow-hidden whitespace-nowrap transition-[max-width,opacity,margin-left] duration-300 ease-out ${
              expanded
                ? "ml-1.5 max-w-[160px] opacity-100"
                : "ml-0 max-w-0 opacity-0"
            }`}
          >
            <span className="min-w-0 truncate">{label}</span>
            <ChevronDown
              size={13}
              className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
            />
          </span>
        </button>
      )}

      {open && (
        <div
          className={
            embedded
              ? "w-full"
              : `dt-popup-up absolute right-0 z-50 ${menuPlacementClass} w-[min(300px,calc(100vw-32px))] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--popover)] shadow-lg backdrop-blur-md`
          }
        >
          {searchable && (
            <div className="flex items-center gap-2 border-b border-[var(--border)] px-3 py-2">
              <Search
                size={13}
                className="shrink-0 text-[var(--muted-foreground)]"
              />
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("Search")}
                className="min-w-0 flex-1 bg-transparent text-[12.5px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
              />
            </div>
          )}
          {filtered.length === 0 ? (
            <div className="px-3 py-4 text-center text-[12px] text-[var(--muted-foreground)]">
              {kind === "skills"
                ? t("No skills available")
                : t("No MCP servers available")}
            </div>
          ) : (
            <div className="max-h-[280px] overflow-y-auto py-1">
              {filtered.map((option) => {
                const active = selected.includes(option.id);
                // A server the deployment switched off cannot answer this turn;
                // it stays listed (and removable if it was already picked) so
                // its absence is explained rather than silent.
                const unavailable = option.available === false;
                const secondary =
                  kind === "skills"
                    ? option.description
                    : [
                        option.provenance_label ||
                          t(option.source || "account"),
                        unavailable ? t("Disabled") : "",
                      ]
                        .filter(Boolean)
                        .join(" · ");
                return (
                  <button
                    key={option.id}
                    type="button"
                    disabled={unavailable && !active}
                    aria-pressed={active}
                    onClick={() => onToggle(option.id)}
                    className={`flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors ${
                      unavailable && !active
                        ? "cursor-not-allowed opacity-45"
                        : active
                          ? "bg-[var(--primary)]/[0.06] active:bg-[var(--muted)]/70"
                          : "hover:bg-[var(--muted)]/45 active:bg-[var(--muted)]/70"
                    }`}
                  >
                    <Icon
                      size={15}
                      strokeWidth={1.7}
                      className={`mt-[2px] shrink-0 ${
                        active
                          ? "text-[var(--primary)]"
                          : "text-[var(--muted-foreground)]"
                      }`}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12.5px] font-medium text-[var(--foreground)]">
                        {option.name}
                      </span>
                      {secondary ? (
                        <span className="mt-0.5 block truncate text-[11px] text-[var(--muted-foreground)]">
                          {secondary}
                        </span>
                      ) : null}
                    </span>
                    {active && (
                      <Check
                        size={14}
                        strokeWidth={2}
                        className="mt-[3px] shrink-0 text-[var(--primary)]"
                      />
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
