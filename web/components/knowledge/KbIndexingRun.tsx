"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "@/shared/api/client";

interface Run {
  task_id: string;
  state: string;
  phase: string;
  started_at: number;
  finished_at?: number;
  last_activity_at: number;
  last_progress_at: number;
  phase_current?: number;
  phase_total?: number;
  usable_version?: string;
  cancel_requested: boolean;
  recovery: string;
  error?: string;
  documents: Record<string, { status: string; reason?: string; detail?: string; parse_reused: boolean }>;
}

export default function KbIndexingRun({ kbName, readOnly = false }: { kbName: string; readOnly?: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<{ key: string; run: Run | null }>();
  const [error, setError] = useState(false);
  const [now, setNow] = useState(Date.now() / 1000);
  const [cancelling, setCancelling] = useState(false);
  const run = snapshot?.key === kbName ? snapshot.run : undefined;
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await apiFetch(`/api/knowledge-bases/${encodeURIComponent(kbName)}/indexing-run`, { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error(String(response.status));
        const data = await response.json() as { run: Run | null };
        if (!controller.signal.aborted) {
          setSnapshot({ key: kbName, run: data.run });
          setError(false);
          setNow(Date.now() / 1000);
        }
      } catch { if (!controller.signal.aborted) setError(true); }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 3000);
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [kbName, open]);
  const cancel = async () => {
    if (!run) return;
    setCancelling(true);
    try {
      const response = await apiFetch(`/api/knowledge-bases/${encodeURIComponent(kbName)}/indexing-run/${encodeURIComponent(run.task_id)}/cancel`, { method: "POST" });
      if (!response.ok) throw new Error(String(response.status));
      setSnapshot({ key: kbName, run: { ...run, cancel_requested: true } });
    } catch { setError(true); }
    finally { setCancelling(false); }
  };
  return <details open={open} className="shrink-0 border-b border-[var(--border)] px-6 py-2 text-xs">
    <summary className="cursor-pointer" onClick={(event) => { event.preventDefault(); setOpen((value) => !value); }}>{t("Indexing recovery details")}</summary>
    {open && <div className="max-h-56 space-y-2 overflow-auto py-2">
      {error && <p role="alert">{t("Could not read indexing state. Refresh and retry.")}</p>}
      {run ? <>
        <p>{t("Run state")}: {t(`indexingState.${run.state}`, { defaultValue: run.state })} · {t("Current phase")}: {t(`indexingPhase.${run.phase}`, { defaultValue: run.phase })}</p>
        <p>{t("Runtime")}: {Math.max(0, Math.floor((run.finished_at || now) - run.started_at))}s · {t("Since activity")}: {Math.max(0, Math.floor(now - run.last_activity_at))}s · {t("Since measurable progress")}: {Math.max(0, Math.floor(now - run.last_progress_at))}s</p>
        <p>{run.phase_total ? `${run.phase_current || 0}/${run.phase_total}` : t("Phase progress is indeterminate.")} {t("Phase completion does not mean the whole index is ready.")}</p>
        {run.usable_version && <p>{t("Verified index version")}: {run.usable_version}</p>}
        <p>{t("Retry reuses validated parser outputs. Interrupted embedding stages restart.")}</p>
        <ul>{Object.entries(run.documents).map(([name, doc]) => <li className="break-words" key={name}>{name}: {t(`indexingDocument.${doc.status}`, { defaultValue: doc.status })}{doc.parse_reused ? ` · ${t("Parse cache reused")}` : ""}{doc.reason ? ` · ${doc.reason}` : ""}{doc.detail ? ` · ${doc.detail}` : ""}</li>)}</ul>
        {run.error && <p role="alert">{run.error}</p>}
        {!readOnly && run.state === "running" && <button className="underline" disabled={cancelling || run.cancel_requested} onClick={() => void cancel()}>{run.cancel_requested ? t("Cancellation pending at a safe boundary") : t("Cancel indexing")}</button>}
      </> : <p>{run === null ? t("No durable indexing run recorded yet.") : t("Loading...")}</p>}
    </div>}
  </details>;
}
