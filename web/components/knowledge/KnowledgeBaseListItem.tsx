"use client";

import { useTranslation } from "react-i18next";
import { Star, Trash2 } from "lucide-react";
import {
  kbHasLiveProgress,
  kbNeedsReindex,
  resolveKbStatus,
  resolveProgressPercent,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";
import KbStatusDot from "./KbStatusDot";

interface KnowledgeBaseListItemProps {
  kb: KnowledgeBase;
  selected: boolean;
  onSelect: () => void;
  onSetDefault: () => void;
  onDelete: () => void;
  isReindexingLocally?: boolean;
}

export default function KnowledgeBaseListItem({
  kb,
  selected,
  onSelect,
  onSetDefault,
  onDelete,
  isReindexingLocally = false,
}: KnowledgeBaseListItemProps) {
  const { t } = useTranslation();
  const status = resolveKbStatus(kb);
  const needsReindex = kbNeedsReindex(kb);
  const isLive = kbHasLiveProgress(kb) || isReindexingLocally;
  const isError = status === "error";
  const isReady = status === "ready" && !needsReindex;
  const percent = resolveProgressPercent(kb.progress);
  const docCount = kb.statistics?.raw_documents ?? 0;

  const subtitle = needsReindex
    ? t("Needs reindex")
    : isError
      ? t("Error")
      : isLive
        ? percent > 0
          ? t("Processing · {{percent}}%", { percent })
          : t("Processing…")
        : isReady
          ? docCount === 1
            ? t("Ready · {{count}} doc", { count: docCount })
            : t("Ready · {{count}} docs", { count: docCount })
          : status.replaceAll("_", " ");

  return (
    <div
      className={`group relative cursor-pointer rounded-lg border px-3 py-2.5 transition-colors ${
        selected
          ? "border-[var(--primary)]/40 bg-[var(--primary)]/8"
          : "border-transparent hover:border-[var(--border)] hover:bg-[var(--muted)]/40"
      }`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="flex items-center gap-2">
        <KbStatusDot kb={kb} isReindexingLocally={isReindexingLocally} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {kb.is_default && (
              <Star
                className="h-3 w-3 shrink-0 text-amber-500"
                fill="currentColor"
              />
            )}
            <span className="truncate text-[13px] font-medium text-[var(--foreground)]">
              {kb.name}
            </span>
            {kb.assigned && (
              <span className="shrink-0 rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-medium text-emerald-700 dark:text-emerald-300">
                {t("Assigned")}
              </span>
            )}
          </div>
          <div className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
            {subtitle}
          </div>
        </div>

        <div
          className={`flex shrink-0 items-center gap-0.5 ${
            selected ? "" : "opacity-0 group-hover:opacity-100"
          } transition-opacity`}
        >
          {!kb.is_default && !kb.read_only && (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onSetDefault();
              }}
              title={t("Set default")}
              className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-amber-500"
            >
              <Star className="h-3 w-3" />
            </button>
          )}
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onDelete();
            }}
            disabled={kb.read_only}
            title={
              kb.read_only
                ? t("Assigned knowledge bases are read-only")
                : t("Delete")
            }
            className="rounded p-1 text-[var(--muted-foreground)] hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-30 dark:hover:bg-red-950/30"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>

      {isLive && (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-[var(--border)]/70">
          <div
            className="h-full rounded-full bg-[var(--primary)] transition-all duration-300"
            style={{ width: `${Math.max(percent, 5)}%` }}
          />
        </div>
      )}
    </div>
  );
}
