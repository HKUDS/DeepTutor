"use client";

import { useTranslation } from "react-i18next";
import ProcessLogs from "@/components/common/ProcessLogs";
import type { TaskState } from "@/hooks/useKnowledgeProgress";
import {
  kbHasLiveProgress,
  progressMessage,
  resolveProgressPercent,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";

/** Shared by all detail tabs so processing logs are visible on arrival. */
export default function KbTaskLogs({
  kb,
  task,
}: {
  kb: KnowledgeBase;
  task?: TaskState;
}) {
  const { t } = useTranslation();
  const executing = task?.executing ?? kbHasLiveProgress(kb);
  const message = kb.progress ? progressMessage(kb.progress, t) : undefined;
  const logs = task?.logs.length ? task.logs : message ? [message] : [];
  if (!task && !executing) return null;
  if (!executing && !logs.length && !task?.error) return null;
  const percent = Math.max(
    0,
    Math.min(100, resolveProgressPercent(kb.progress)),
  );

  return (
    <section
      aria-label={t("Process Logs")}
      className="shrink-0 space-y-2 border-b border-[var(--border)] px-6 py-3"
    >
      <ProcessLogs
        logs={logs}
        executing={executing}
        title={t("Process Logs")}
        emptyMessage={t("Waiting for output...")}
      />
      {executing && (
        <div className="flex items-center gap-3">
          <div
            role="progressbar"
            aria-label={t("Processing live")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--border)]/70"
          >
            <div
              className="h-full rounded-full bg-[var(--primary)] transition-all duration-300"
              style={{ width: `${Math.max(percent, 4)}%` }}
            />
          </div>
          <span className="text-[11px] text-[var(--muted-foreground)]">
            {percent}%
          </span>
        </div>
      )}
      {task?.error && (
        <p
          role="alert"
          className="whitespace-pre-wrap break-words text-xs text-red-600 dark:text-red-300"
        >
          {task.error}
        </p>
      )}
    </section>
  );
}
