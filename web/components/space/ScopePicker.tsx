"use client";

import { Check, ChevronDown, ChevronRight, FolderOpen } from "lucide-react";
import { CalendarDays } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { formatRelativeTime } from "@/lib/relative-time";
import type { SelectGroup, SelectionUnit } from "@/lib/chat-import";

/**
 * Unit-level scope picker shared by the import wizard and "Edit scope". The
 * selection unit is the *group* (a project for Claude Code, a day for Codex):
 * checking a unit brings in all of its conversations and locks the agent to it,
 * so a later sync pulls new conversations inside chosen units and nothing else.
 * Sessions are shown expanded as a read-only preview — they aren't individually
 * selectable, which is what keeps "what I picked" and "what syncs" the same.
 */
export interface ScopePickerProps {
  groups: SelectGroup[];
  unit: SelectionUnit;
  /** Selected group keys (cwds or `YYYY-MM-DD`). */
  selected: Set<string>;
  onToggle: (key: string) => void;
  onSelectAll: () => void;
  onClearAll: () => void;
  lang: string;
}

function formatDay(key: string, lang: string): string {
  const d = new Date(`${key}T00:00:00`);
  if (Number.isNaN(d.getTime())) return key;
  return d.toLocaleDateString(lang, {
    year: "numeric",
    month: "short",
    day: "numeric",
    weekday: "short",
  });
}

export default function ScopePicker({
  groups,
  unit,
  selected,
  onToggle,
  onSelectAll,
  onClearAll,
  lang,
}: ScopePickerProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const totalSessions = groups.reduce((n, g) => n + g.sessions.length, 0);
  const selectedSessions = groups.reduce(
    (n, g) => (selected.has(g.key) ? n + g.sessions.length : n),
    0,
  );
  const GroupIcon = unit === "dates" ? CalendarDays : FolderOpen;

  const toggleExpand = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[11.5px] text-[var(--muted-foreground)]">
          {unit === "dates"
            ? t("{{days}} days · {{sessions}} conversations", {
                days: groups.length,
                sessions: totalSessions,
              })
            : t("{{projects}} projects · {{sessions}} conversations", {
                projects: groups.length,
                sessions: totalSessions,
              })}
          {selectedSessions > 0 ? (
            <span className="ml-1.5 font-medium text-[var(--foreground)]">
              · {t("{{count}} selected", { count: selectedSessions })}
            </span>
          ) : null}
        </span>
        <div className="flex items-center gap-1 text-[11.5px] font-medium">
          <button
            type="button"
            onClick={onSelectAll}
            className="rounded-md px-2 py-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)]"
          >
            {t("Select all")}
          </button>
          <button
            type="button"
            onClick={onClearAll}
            className="rounded-md px-2 py-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)]"
          >
            {t("Clear")}
          </button>
        </div>
      </div>

      <div className="max-h-[44vh] space-y-1.5 overflow-y-auto pr-1">
        {groups.map((group) => {
          const checked = selected.has(group.key);
          const isOpen = expanded.has(group.key);
          return (
            <div
              key={group.key}
              className={`overflow-hidden rounded-xl border transition-colors ${
                checked
                  ? "border-[var(--primary)]/40 bg-[var(--primary)]/[0.04]"
                  : "border-[var(--border)]/60 bg-[var(--card)]/40"
              }`}
            >
              <div className="flex items-center gap-2.5 px-2.5 py-2">
                <button
                  type="button"
                  onClick={() => onToggle(group.key)}
                  aria-label={t("Select")}
                  aria-pressed={checked}
                  className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                    checked
                      ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "border-[var(--border)] bg-transparent hover:border-[var(--primary)]/60"
                  }`}
                >
                  {checked ? <Check size={11} strokeWidth={3} /> : null}
                </button>
                <button
                  type="button"
                  onClick={() => toggleExpand(group.key)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                >
                  {isOpen ? (
                    <ChevronDown
                      size={14}
                      className="shrink-0 text-[var(--muted-foreground)]"
                    />
                  ) : (
                    <ChevronRight
                      size={14}
                      className="shrink-0 text-[var(--muted-foreground)]"
                    />
                  )}
                  <GroupIcon
                    size={14}
                    className="shrink-0 text-[var(--muted-foreground)]"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12.5px] font-medium text-[var(--foreground)]">
                      {unit === "dates"
                        ? formatDay(group.label, lang)
                        : group.label}
                    </span>
                    {group.sublabel ? (
                      <span className="block truncate text-[10.5px] text-[var(--muted-foreground)]/80">
                        {group.sublabel}
                      </span>
                    ) : null}
                  </span>
                </button>
                <span className="shrink-0 text-[10.5px] text-[var(--muted-foreground)]">
                  {t("{{count}} chats", { count: group.sessions.length })}
                </span>
              </div>

              {isOpen && (
                <ul className="divide-y divide-[var(--border)]/40 border-t border-[var(--border)]/40">
                  {group.sessions.map((session) => (
                    <li
                      key={session.externalId}
                      className="flex items-center gap-2.5 px-3 py-2 pl-9"
                    >
                      <span className="min-w-0 flex-1 truncate text-[12px] text-[var(--muted-foreground)]">
                        {session.provisionalTitle || t("Untitled conversation")}
                      </span>
                      <span className="shrink-0 text-[10.5px] text-[var(--muted-foreground)]/70">
                        {formatRelativeTime(session.lastModified / 1000, lang)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
