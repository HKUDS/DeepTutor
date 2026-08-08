"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Download, RefreshCw, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAuthStatus } from "@/hooks/useAuthStatus";
import {
  fetchUpdateJob,
  requestWebUpdate,
  type UpdateJobStatus,
} from "@/lib/update-api";
import { notify } from "@/lib/notifications";
import { normalizeVersionTag } from "@/lib/version";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

interface UpdateActionProps {
  targetVersion: string | null;
  actionAvailable: boolean;
}

type UpdatePhase =
  "idle" | "requesting" | "updating" | "restarting" | "reconnected" | "failed";

const POLL_INTERVAL_MS = 750;
const POLL_TIMEOUT_MS = 120_000;

function phaseForStatus(status: UpdateJobStatus): UpdatePhase {
  if (status === "restarting") return "restarting";
  if (status === "succeeded") return "reconnected";
  if (status === "failed") return "failed";
  return "updating";
}

function isActiveStatus(status: UpdateJobStatus): boolean {
  return ["pending", "handoff", "running", "restarting"].includes(status);
}

export function UpdateAction({
  targetVersion,
  actionAvailable,
}: UpdateActionProps) {
  const { t } = useTranslation();
  const { enabled, isAdmin, loading } = useAuthStatus();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [phase, setPhase] = useState<UpdatePhase>("idle");
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    const deadline = Date.now() + POLL_TIMEOUT_MS;
    const restoreJob = async () => {
      try {
        const job = await fetchUpdateJob(controller.signal);
        if (!job) return;
        const sameTarget =
          targetVersion === null ||
          (normalizeVersionTag(job.target_version) ?? job.target_version) ===
            targetVersion;
        if (isActiveStatus(job.status) || sameTarget) {
          setPhase(phaseForStatus(job.status));
          setPolling(isActiveStatus(job.status));
        }
      } catch {
        if (!controller.signal.aborted && Date.now() < deadline) {
          retryTimer = setTimeout(restoreJob, POLL_INTERVAL_MS);
        }
      }
    };
    void restoreJob();
    return () => {
      controller.abort();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [actionAvailable, targetVersion]);

  useEffect(() => {
    if (!polling) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = Date.now() + POLL_TIMEOUT_MS;

    const poll = async () => {
      try {
        const job = await fetchUpdateJob();
        if (cancelled) return;
        if (job) {
          const nextPhase = phaseForStatus(job.status);
          setPhase(nextPhase);
          if (nextPhase === "reconnected" || nextPhase === "failed") {
            setPolling(false);
            return;
          }
        }
      } catch {
        if (cancelled) return;
        setPhase("restarting");
      }

      if (Date.now() >= deadline) {
        setPhase("failed");
        setPolling(false);
        return;
      }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [polling]);

  const startUpdate = useCallback(async () => {
    setPhase("requesting");
    try {
      const job = await requestWebUpdate();
      setDialogOpen(false);
      setPhase(phaseForStatus(job.status));
      setPolling(true);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : (t("Update failed") as string);
      setPhase("failed");
      notify(message, { tone: "error" });
    }
  }, [t]);

  if (loading || (enabled && !isAdmin)) return null;
  if (!actionAvailable && phase === "idle") return null;

  const labels: Record<UpdatePhase, string> = {
    idle: t("Update and restart") as string,
    requesting: t("Starting update…") as string,
    updating: t("Updating…") as string,
    restarting: t("Restarting…") as string,
    reconnected: t("Reconnected") as string,
    failed: t("Update failed") as string,
  };
  const busy = ["requesting", "updating", "restarting"].includes(phase);
  const Icon =
    phase === "idle"
      ? Download
      : phase === "reconnected"
        ? Check
        : phase === "failed"
          ? TriangleAlert
          : RefreshCw;
  const buttonLabel =
    phase === "idle" && targetVersion
      ? `${labels[phase]}: ${targetVersion}`
      : labels[phase];
  const tone =
    phase === "reconnected"
      ? "bg-emerald-500/10 text-emerald-700 shadow-[0_0_0_1px_rgba(16,185,129,0.18),0_1px_2px_rgba(0,0,0,0.05)] dark:text-emerald-300"
      : phase === "failed"
        ? "bg-rose-500/10 text-rose-700 shadow-[0_0_0_1px_rgba(244,63,94,0.18),0_1px_2px_rgba(0,0,0,0.05)] hover:bg-rose-500/20 dark:text-rose-300"
        : "bg-sky-500/10 text-sky-700 shadow-[0_0_0_1px_rgba(14,165,233,0.18),0_1px_2px_rgba(0,0,0,0.05)] hover:bg-sky-500/20 hover:shadow-[0_0_0_1px_rgba(14,165,233,0.28),0_2px_4px_rgba(0,0,0,0.07)] dark:text-sky-300";

  return (
    <>
      <button
        type="button"
        data-testid="update-action"
        data-phase={phase}
        onClick={() => setDialogOpen(true)}
        disabled={!actionAvailable || busy || phase === "reconnected"}
        title={buttonLabel}
        aria-label={buttonLabel}
        className={`relative flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-[background-color,color,box-shadow,scale,opacity] duration-150 ease-out active:not-disabled:scale-[0.96] disabled:cursor-default disabled:opacity-70 ${tone}`}
      >
        <Icon
          aria-hidden="true"
          size={13}
          strokeWidth={2}
          className={busy ? "animate-spin" : undefined}
        />
        <span className="sr-only">{labels[phase]}</span>
      </button>

      <ConfirmDialog
        open={dialogOpen}
        title={t("Update and restart DeepTutor?") as string}
        confirmLabel={t("Update and restart") as string}
        cancelLabel={t("Cancel") as string}
        busy={phase === "requesting"}
        busyLabel={t("Starting update…") as string}
        onConfirm={() => void startUpdate()}
        onCancel={() => setDialogOpen(false)}
      >
        {
          t(
            "DeepTutor will stop briefly, install {{version}}, and restart with the same settings.",
            { version: targetVersion ?? "" },
          ) as string
        }
      </ConfirmDialog>
    </>
  );
}
