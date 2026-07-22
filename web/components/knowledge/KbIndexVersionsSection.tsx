"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Layers,
  Loader2,
  RefreshCw,
  Star,
} from "lucide-react";
import {
  formatKnowledgeTimestamp,
  kbCanReindex,
  kbNeedsReindex,
  resolveKbStatus,
  resolveProgressPercent,
  type IndexVersion,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";
import type { TaskState } from "@/hooks/useKnowledgeProgress";
import ProcessLogs from "@/components/common/ProcessLogs";

interface KbIndexVersionsSectionProps {
  kb: KnowledgeBase;
  task?: TaskState;
  onReindex: () => Promise<void>;
}

export default function KbIndexVersionsSection({
  kb,
  task,
  onReindex,
}: KbIndexVersionsSectionProps) {
  const { t } = useTranslation();
  const [submitting, setSubmitting] = useState(false);
  const versions = kb.statistics?.index_versions ?? [];
  const activeSig = kb.statistics?.active_signature ?? null;
  const needsReindex = kbNeedsReindex(kb);
  const isError = resolveKbStatus(kb) === "error";
  const mismatch = Boolean(kb.metadata?.embedding_mismatch);
  const isReindexingHere =
    (task?.kind === "reindex" || task?.kind === "retry") && task.executing;
  const percent = resolveProgressPercent(kb.progress);
  const lastIndexed = formatKnowledgeTimestamp(kb.metadata?.last_indexed_at);
  const lastIndexedCount = kb.metadata?.last_indexed_count;

  const handleReindex = async () => {
    setSubmitting(true);
    try {
      await onReindex();
    } finally {
      setSubmitting(false);
    }
  };

  const showReindexCta = kbCanReindex(kb);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Layers className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
          <div>
            <div className="text-[12.5px] font-medium text-[var(--foreground)]">
              {t("Index versions")}
              <span className="ml-2 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-normal text-[var(--muted-foreground)]">
                {versions.length}
              </span>
            </div>
            <p className="text-[11px] text-[var(--muted-foreground)]">
              {t(
                "Each embedding configuration gets its own stored vector index.",
              )}
            </p>
          </div>
        </div>

        {showReindexCta && (
          <button
            type="button"
            onClick={handleReindex}
            disabled={submitting || isReindexingHere}
            title={
              isError
                ? t(
                    "Retry indexing from the documents already stored in this knowledge base.",
                  )
                : t(
                    "Click Re-index to rebuild this knowledge base with the active embedding model. Existing index versions are preserved.",
                  )
            }
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1 text-[12px] font-medium transition-colors disabled:opacity-50 ${
              isError
                ? "border-red-200 bg-red-50 text-red-700 hover:bg-red-100 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300"
                : "border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300"
            }`}
          >
            {submitting || isReindexingHere ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
            {isReindexingHere
              ? isError
                ? t("Retrying…")
                : t("Re-indexing…")
              : isError
                ? t("Retry indexing")
                : t("Re-index")}
          </button>
        )}
      </div>

      {(isError || needsReindex || mismatch) && (
        <div
          className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-[12px] ${
            isError
              ? "border-red-200 bg-red-50/80 text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-300"
              : "border-amber-200 bg-amber-50/80 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-300"
          }`}
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            {isError
              ? t(
                  "Previous indexing failed. Retry will rebuild the index from the existing source documents.",
                )
              : t(
                  "The active embedding configuration doesn't match any ready index version. Re-index to rebuild against the current embedding model.",
                )}
          </span>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-[var(--border)] bg-[var(--muted)]/30 px-3 py-2 text-[11.5px] text-[var(--muted-foreground)]">
        <Clock className="h-3.5 w-3.5 shrink-0" />
        <span>
          {t("Last indexed")}:{" "}
          <span className="font-medium text-[var(--foreground)]">
            {lastIndexed || t("Not recorded yet")}
          </span>
        </span>
        {typeof lastIndexedCount === "number" && (
          <span>
            ·{" "}
            {t(
              lastIndexedCount === 1
                ? "{{count}} indexed doc"
                : "{{count}} indexed docs",
              { count: lastIndexedCount },
            )}
          </span>
        )}
      </div>

      {versions.length > 0 ? (
        <ul className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)] bg-[var(--background)]">
          {versions.map((version) => (
            <IndexVersionRow
              key={
                version.signature ??
                `${version.model}-${version.dimension}-${version.created_at}`
              }
              version={version}
              activeSignature={activeSig}
            />
          ))}
        </ul>
      ) : (
        <div className="rounded-lg border border-dashed border-[var(--border)] px-4 py-6 text-center text-[12px] text-[var(--muted-foreground)]">
          {t("No index versions yet.")}
        </div>
      )}

      {(task?.kind === "reindex" || task?.kind === "retry") &&
        (task.taskId || task.logs.length > 0 || task.executing) && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[11px] text-[var(--muted-foreground)]">
              <span>
                {task.label}
                {task.taskId ? ` · ${task.taskId}` : ""}
              </span>
              {task.executing && percent > 0 && (
                <span className="font-medium text-[var(--foreground)]">
                  {percent}%
                </span>
              )}
            </div>
            <ProcessLogs
              logs={task.logs}
              executing={task.executing}
              title={t("Re-index Process")}
            />
            {task.executing && (
              <div className="h-1.5 overflow-hidden rounded-full bg-[var(--border)]/70">
                <div
                  className="h-full rounded-full bg-[var(--primary)] transition-all duration-300"
                  style={{ width: `${Math.max(percent, 4)}%` }}
                />
              </div>
            )}
            {task.error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed">
                  {task.error}
                </pre>
              </div>
            )}
          </div>
        )}
    </div>
  );
}

function IndexVersionRow({
  version,
  activeSignature,
}: {
  version: IndexVersion;
  activeSignature: string | null;
}) {
  const { t } = useTranslation();
  const matchesActive =
    !!version.signature && version.signature === activeSignature;
  const isActive = matchesActive && version.ready === true;
  const isPhantom = matchesActive && version.ready !== true;
  const isLegacy = !!version.legacy;

  const title = isLegacy
    ? t("Legacy index")
    : version.model
      ? version.model
      : (version.signature ?? t("Unknown"));

  const created = formatKnowledgeTimestamp(version.created_at);

  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <div
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${
          isActive
            ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-300"
            : isPhantom
              ? "bg-amber-100 text-amber-600 dark:bg-amber-950/30 dark:text-amber-300"
              : "bg-[var(--muted)] text-[var(--muted-foreground)]"
        }`}
        title={
          isActive
            ? t("Active version")
            : isPhantom
              ? t("Stale (matches active config but storage is empty)")
              : isLegacy
                ? t("Legacy index format")
                : t("Inactive version")
        }
      >
        {isActive ? (
          <Star className="h-3.5 w-3.5" fill="currentColor" />
        ) : isPhantom ? (
          <AlertTriangle className="h-3.5 w-3.5" />
        ) : isLegacy ? (
          <Clock className="h-3.5 w-3.5" />
        ) : (
          <CheckCircle2 className="h-3.5 w-3.5" />
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span
            className={`truncate text-[12.5px] font-medium ${
              isPhantom
                ? "text-amber-700 line-through decoration-amber-400/70 dark:text-amber-300"
                : "text-[var(--foreground)]"
            }`}
          >
            {title}
          </span>
          {isActive && (
            <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">
              {t("Active")}
            </span>
          )}
          {isPhantom && (
            <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
              {t("Stale")}
            </span>
          )}
          {isLegacy && !isActive && (
            <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
              {t("Legacy")}
            </span>
          )}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10.5px] text-[var(--muted-foreground)]">
          {typeof version.dimension === "number" && (
            <span>
              {version.dimension}
              {t("d")}
            </span>
          )}
          {version.binding && <span>{version.binding}</span>}
          {created && <span>{created}</span>}
          {version.signature && (
            <span className="font-mono">{version.signature.slice(0, 10)}</span>
          )}
        </div>
      </div>
    </li>
  );
}
