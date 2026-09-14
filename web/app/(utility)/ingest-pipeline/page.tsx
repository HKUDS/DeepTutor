"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Loader2,
  Play,
  RefreshCw,
  SkipForward,
  XCircle,
} from "lucide-react";

import { fetchAuthStatus } from "@/lib/auth";
import {
  fetchIngestPipeline,
  INGEST_STAGE_ORDER,
  retryIngestStage,
  startIngestPipeline,
  type IngestRun,
  type IngestStage,
  type IngestStageName,
  type IngestStageStatus,
} from "@/lib/ingest-pipeline-api";

// Teacher/admin self-service only; the backend enforces the same gate with 403.
const ALLOWED_ROLES = new Set(["admin", "teacher"]);

const STAGE_LABEL_KEY: Record<IngestStageName, string> = {
  structured: "Structure check",
  qb_generated: "Question bank generation",
  kp_mapped: "KP mapping",
  qb_mounted: "Question bank mounting",
};

function StatusBadge({ status, t }: { status: IngestStageStatus; t: (k: string) => string }) {
  const map: Record<
    IngestStageStatus,
    { cls: string; icon: ReactNode; label: string }
  > = {
    queued: {
      cls: "bg-[var(--muted)]/60 text-[var(--muted-foreground)]",
      icon: <CircleDashed className="h-3.5 w-3.5" />,
      label: t("Queued"),
    },
    running: {
      cls: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
      icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
      label: t("Running"),
    },
    done: {
      cls: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
      icon: <CheckCircle2 className="h-3.5 w-3.5" />,
      label: t("Done"),
    },
    failed: {
      cls: "bg-red-500/15 text-red-600 dark:text-red-400",
      icon: <XCircle className="h-3.5 w-3.5" />,
      label: t("Failed"),
    },
    skipped: {
      cls: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
      icon: <SkipForward className="h-3.5 w-3.5" />,
      label: t("Skipped"),
    },
  };
  const meta = map[status] ?? map.queued;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${meta.cls}`}
    >
      {meta.icon}
      {meta.label}
    </span>
  );
}

function stageMetric(stage: IngestStage): string {
  const parts: string[] = [];
  if (typeof stage.node_count === "number") parts.push(`${stage.node_count} nodes`);
  if (typeof stage.count === "number") parts.push(`${stage.count} questions`);
  if (typeof stage.tokens === "number") parts.push(`${stage.tokens} tokens`);
  if (typeof stage.mapped === "number") parts.push(`${stage.mapped} mapped`);
  if (typeof stage.unmapped === "number") parts.push(`${stage.unmapped} unmapped`);
  if (typeof stage.mounted === "number") parts.push(`${stage.mounted} KPs`);
  return parts.join(" · ");
}

export default function IngestPipelinePage() {
  const router = useRouter();
  const { t } = useTranslation();

  const [kbName, setKbName] = useState("");
  const [bookId, setBookId] = useState("");
  const [run, setRun] = useState<IngestRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [retrying, setRetrying] = useState<string>("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [allowed, setAllowed] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const pollFailuresRef = useRef(0);

  const isActive = useCallback(
    (r: IngestRun | null) =>
      !!r &&
      (r.status === "running" ||
        r.status === "queued" ||
        Object.values(r.stages).some((s) => s.status === "running" || s.status === "queued")),
    [],
  );

  const poll = useCallback(
    async (kb: string, book: string) => {
      try {
        const latest = await fetchIngestPipeline(kb, book);
        if (!mountedRef.current) return;
        pollFailuresRef.current = 0;
        setRun(latest);
        if (latest && isActive(latest)) {
          timerRef.current = setTimeout(() => void poll(kb, book), 2000);
        } else {
          setBusy(false);
          setRetrying("");
        }
      } catch (e) {
        if (!mountedRef.current) return;
        // 单次网络抖动不放弃：有限次退避续链（后端可能还在跑），
        // 连续失败才停链报错，避免界面永久卡在 running。
        pollFailuresRef.current += 1;
        if (pollFailuresRef.current <= 5) {
          timerRef.current = setTimeout(() => void poll(kb, book), 5000);
          return;
        }
        setBusy(false);
        setRetrying("");
        setError(e instanceof Error ? e.message : t("Failed to load pipeline status"));
      }
    },
    [isActive, t],
  );

  useEffect(() => {
    mountedRef.current = true;
    fetchAuthStatus().then((status) => {
      if (!status?.authenticated) {
        router.replace("/login");
        return;
      }
      if (!ALLOWED_ROLES.has(status.role ?? "")) {
        router.replace("/");
        return;
      }
      setAllowed(true);
    });
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [router]);

  const start = useCallback(async () => {
    if (!kbName.trim() || !bookId.trim()) return;
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const { run: started } = await startIngestPipeline(kbName.trim(), bookId.trim());
      setRun(started);
      await poll(kbName.trim(), bookId.trim());
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : t("Failed to start pipeline"));
    }
  }, [kbName, bookId, poll, t]);

  const retry = useCallback(
    async (stage: IngestStageName) => {
      if (!run) return;
      setError("");
      setRetrying(stage);
      try {
        const { run: updated } = await retryIngestStage(run.run_id, stage);
        setRun(updated);
        await poll(run.kb_name, run.book_id);
      } catch (e) {
        setRetrying("");
        setError(e instanceof Error ? e.message : t("Failed to retry stage"));
      }
    },
    [run, poll, t],
  );

  if (!allowed) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 text-center text-sm text-[var(--muted-foreground)]">
        {t("Checking access…")}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-[var(--foreground)]">
          {t("Material pipeline")}
        </h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {t("Run the four-stage material pipeline: structure check, question bank generation, KP mapping, mounting")}
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </div>
      )}
      {notice && (
        <div className="mb-4 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-600 dark:text-emerald-400">
          {notice}
        </div>
      )}

      <section className="mb-6 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">
              {t("Knowledge base name")}
            </span>
            <input
              value={kbName}
              onChange={(e) => setKbName(e.target.value)}
              placeholder="e.g. politics-grade10"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] outline-none transition-colors focus:border-teal-500/60"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">
              {t("Book ID")}
            </span>
            <input
              value={bookId}
              onChange={(e) => setBookId(e.target.value)}
              placeholder="e.g. bk_politics_g10"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] outline-none transition-colors focus:border-teal-500/60"
            />
          </label>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={() => void start()}
            disabled={busy || !kbName.trim() || !bookId.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-4 py-2 text-sm font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {t("Start pipeline")}
          </button>
          {run && (
            <span className="text-xs text-[var(--muted-foreground)]">
              {t("Run")}: <code className="font-mono">{run.run_id}</code>
            </span>
          )}
        </div>
      </section>

      {run && (
        <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--foreground)]">
              {t("Pipeline stages")}
            </h2>
            <span className="text-xs text-[var(--muted-foreground)]">
              {t("Overall")}: {t(run.status)}
            </span>
          </div>
          <ol className="space-y-3">
            {INGEST_STAGE_ORDER.map((stageKey, idx) => {
              const stage = run.stages[stageKey];
              const status: IngestStageStatus = stage?.status ?? "queued";
              const canRetry =
                !busy &&
                (status === "failed" || status === "skipped" || status === "done") &&
                retrying !== stageKey;
              return (
                <li
                  key={stageKey}
                  className="rounded-xl border border-[var(--border)] bg-[var(--background)] px-4 py-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2 text-sm text-[var(--foreground)]">
                      <ChevronRight className="h-4 w-4 text-[var(--muted-foreground)]" />
                      <span className="font-medium">
                        {idx + 1}. {t(STAGE_LABEL_KEY[stageKey])}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={status} t={t} />
                      <button
                        type="button"
                        onClick={() => void retry(stageKey)}
                        disabled={!canRetry}
                        title={t("Retry this stage")}
                        className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted-foreground)] transition-colors hover:bg-[var(--card)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {retrying === stageKey ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <RefreshCw className="h-3.5 w-3.5" />
                        )}
                        {t("Retry")}
                      </button>
                    </div>
                  </div>
                  {stage?.note && (
                    <p className="mt-2 pl-6 text-xs leading-relaxed text-[var(--muted-foreground)]">
                      {stage.note}
                    </p>
                  )}
                  {stage && stageMetric(stage) && (
                    <p className="mt-1 pl-6 text-xs font-medium tabular-nums text-[var(--foreground)]/70">
                      {stageMetric(stage)}
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </div>
  );
}
