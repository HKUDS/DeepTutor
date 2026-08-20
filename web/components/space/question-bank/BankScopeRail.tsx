"use client";

import { useTranslation } from "react-i18next";
import { Bookmark, FolderOpen, Inbox, LayoutGrid, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { NotebookCategory, QuestionBankStats } from "@/lib/notebook-api";
import type { BankScope } from "./useQuestionBank";

interface BankScopeRailProps {
  scope: BankScope;
  stats: QuestionBankStats;
  categories: NotebookCategory[];
  onSelect: (scope: BankScope) => void;
}

const STATUS_SCOPES: {
  kind: "all" | "wrong" | "bookmarked" | "uncategorized";
  label: string;
  icon: LucideIcon;
  count: (stats: QuestionBankStats) => number;
}[] = [
  { kind: "all", label: "All", icon: LayoutGrid, count: (s) => s.total },
  { kind: "wrong", label: "Wrong Only", icon: XCircle, count: (s) => s.wrong },
  {
    kind: "bookmarked",
    label: "Bookmarked",
    icon: Bookmark,
    count: (s) => s.bookmarked,
  },
  {
    kind: "uncategorized",
    label: "Unfiled",
    icon: Inbox,
    count: (s) => s.uncategorized,
  },
];

/**
 * The view switcher, with live counts on every chip.
 *
 * "Unfiled" is deliberately a first-class view: it is the pile the learner
 * actually wants to work through when they say the bank needs tidying, and
 * without a count they cannot tell whether the work is done.
 */
export default function BankScopeRail({
  scope,
  stats,
  categories,
  onSelect,
}: BankScopeRailProps) {
  const { t } = useTranslation();

  const chipClass = (active: boolean) =>
    `inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12.5px] transition-colors ${
      active
        ? "bg-[var(--foreground)] font-medium text-[var(--background)]"
        : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
    }`;

  return (
    <div className="flex items-center gap-1 overflow-x-auto pb-0.5">
      {STATUS_SCOPES.map(({ kind, label, icon: Icon, count }) => {
        const active = scope.kind === kind;
        return (
          <button
            key={kind}
            type="button"
            onClick={() => onSelect({ kind })}
            className={chipClass(active)}
          >
            <Icon className="h-3.5 w-3.5" />
            {t(label)}
            <span
              className={`tabular-nums text-[11px] ${
                active
                  ? "text-[var(--background)]/70"
                  : "text-[var(--muted-foreground)]"
              }`}
            >
              {count(stats)}
            </span>
          </button>
        );
      })}

      {categories.length > 0 && (
        <span className="mx-1 h-4 w-px shrink-0 bg-[var(--border)]" />
      )}

      {categories.map((category) => {
        const active =
          scope.kind === "category" && scope.categoryId === category.id;
        return (
          <button
            key={category.id}
            type="button"
            onClick={() =>
              onSelect({ kind: "category", categoryId: category.id })
            }
            className={chipClass(active)}
          >
            <FolderOpen className="h-3.5 w-3.5" />
            <span className="max-w-[10rem] truncate">{category.name}</span>
            <span
              className={`tabular-nums text-[11px] ${
                active
                  ? "text-[var(--background)]/70"
                  : "text-[var(--muted-foreground)]"
              }`}
            >
              {category.entry_count}
            </span>
          </button>
        );
      })}
    </div>
  );
}
