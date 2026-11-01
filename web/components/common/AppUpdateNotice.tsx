"use client";

/**
 * Global update surface, mounted once by AppShell.
 *
 * The sidebar's VersionBadge already shows a dot, but acting on an update
 * required opening Settings → About. This brings the same flow to every page:
 * a launch-time check, a persistent notice with the release summary, an
 * admin-only "update and restart" action, live job progress while the
 * launcher replaces the package, and a "what's new" dialog on the first start
 * after an update.
 *
 * The check is intentionally lazy: the backend caches release metadata for
 * 24 hours, and this component only asks on mount, every six hours while the
 * tab stays open, and when the tab becomes visible again.
 */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  Download,
  RotateCw,
  Sparkles,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import Button from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  fetchAppUpdateJob,
  fetchAppUpdateStatus,
  requestAppUpdate,
  subscribeAppUpdateStatus,
  updateJobIsActive,
  type AppUpdateStatus,
  type UpdateJob,
} from "@/lib/app-update";
import { notify } from "@/lib/notifications";
import { browserStorage } from "@/shared/storage";

const DISMISSED_VERSION_KEY = "dt:app-update:dismissed-version";
const SEEN_VERSION_KEY = "dt:app-update:seen-version";
const SEEN_JOB_KEY = "dt:app-update:seen-job";
const RECHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;
const POLL_INTERVAL_MS = 1000;

interface WhatsNew {
  version: string;
  excerpt: string;
  url: string;
}

export default function AppUpdateNotice() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<AppUpdateStatus | null>(null);
  const [job, setJob] = useState<UpdateJob | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const [dismissedVersion, setDismissedVersion] = useState<string | null>(null);
  const [seenJobId, setSeenJobId] = useState<string | null>(null);
  const [whatsNew, setWhatsNew] = useState<WhatsNew | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [actionError, setActionError] = useState("");
  const refreshRef = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    // localStorage is a post-mount external store; reading it during render
    // would make the server and client trees disagree.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDismissedVersion(browserStorage.readRaw("local", DISMISSED_VERSION_KEY));
    setSeenJobId(browserStorage.readRaw("local", SEEN_JOB_KEY));
    setHydrated(true);
  }, []);

  // Automatic check: on launch, on a six-hour cadence, and when the tab
  // returns to the foreground. The server caches the GitHub response for 24h.
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const refresh = async () => {
      try {
        const next = await fetchAppUpdateStatus(controller.signal);
        if (!active) return;
        setStatus(next);
        setJob(next.job);
      } catch {
        // Offline / rate-limited: the About page owns the detailed error.
      }
    };
    refreshRef.current = refresh;
    void refresh();
    const timer = window.setInterval(() => void refresh(), RECHECK_INTERVAL_MS);
    const onVisibility = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisibility);
    const unsubscribe = subscribeAppUpdateStatus((signal) => {
      if (!active) return;
      if (signal.status) {
        setStatus(signal.status);
        setJob(signal.status.job);
      }
    });
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      unsubscribe();
    };
  }, []);

  // Remember the running version on a first install, and show the release
  // summary once when the version changes after an update.
  useEffect(() => {
    if (!hydrated || !status) return;
    const current = status.current_version;
    if (!current) return;
    const seen = browserStorage.readRaw("local", SEEN_VERSION_KEY);
    if (!seen) {
      browserStorage.writeRaw("local", SEEN_VERSION_KEY, current);
      return;
    }
    if (seen === current) return;
    browserStorage.writeRaw("local", SEEN_VERSION_KEY, current);
    if (!status.check_enabled || status.update_available) return;
    const release = status.release;
    if (!release || release.version !== current || !release.excerpt.trim()) return;
    // Opening the post-update dialog is the external event this effect
    // synchronizes; it is guarded by the persisted seen version.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setWhatsNew({
      version: current,
      excerpt: release.excerpt,
      url: release.url,
    });
  }, [hydrated, status]);

  const activeJob = job && updateJobIsActive(job.status) ? job : null;
  const activeJobStatus = activeJob?.status ?? null;

  // Poll while the launcher owns the update. The backend disappears during
  // the restart, so fetch errors are expected and simply retried.
  useEffect(() => {
    if (!activeJobStatus) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await fetchAppUpdateJob();
        if (cancelled) return;
        if (next) {
          setJob(next);
          if (next.status === "succeeded") {
            browserStorage.writeRaw("local", SEEN_JOB_KEY, next.id);
            setSeenJobId(next.id);
            // The status refresh will report the new current version; until
            // it lands, do not flash the old "update available" card again.
            browserStorage.writeRaw(
              "local",
              DISMISSED_VERSION_KEY,
              next.target_version,
            );
            setDismissedVersion(next.target_version);
            notify(
              t("DeepTutor updated to {{version}}.", {
                version: next.target_version,
              }),
              { tone: "success", durationMs: 8000 },
            );
            void refreshRef.current();
            return;
          }
          if (next.status === "failed") return;
        }
      } catch {
        // The backend is restarting; keep polling.
      }
      if (!cancelled) timer = setTimeout(poll, POLL_INTERVAL_MS);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [activeJobStatus, t]);

  useEffect(() => {
    if (!whatsNew) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setWhatsNew(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [whatsNew]);

  const dismiss = useCallback(() => {
    const version = status?.release?.version;
    if (!version) return;
    browserStorage.writeRaw("local", DISMISSED_VERSION_KEY, version);
    setDismissedVersion(version);
    setActionError("");
  }, [status?.release?.version]);

  const dismissFailedJob = useCallback(() => {
    if (!job) return;
    browserStorage.writeRaw("local", SEEN_JOB_KEY, job.id);
    setSeenJobId(job.id);
  }, [job]);

  const update = useCallback(async () => {
    setRequesting(true);
    setActionError("");
    try {
      const next = await requestAppUpdate();
      setJob(next);
      setConfirmOpen(false);
    } catch (cause) {
      setActionError(
        cause instanceof Error
          ? cause.message
          : (t("Unable to start the update.") as string),
      );
    } finally {
      setRequesting(false);
    }
  }, [t]);

  const version = status?.release?.version ?? "";
  const canUpdate = Boolean(
    status?.is_admin &&
      status.installation.automatic_update &&
      status.launcher_managed,
  );
  const showUpdate = Boolean(
    hydrated &&
      status?.check_enabled &&
      status.update_available &&
      version &&
      version !== dismissedVersion &&
      !activeJob,
  );
  const showFailed =
    hydrated && job?.status === "failed" && job.id !== seenJobId && !activeJob;

  if (!showUpdate && !activeJob && !showFailed && !whatsNew) return null;

  return (
    <>
      {(showUpdate || activeJob || showFailed) && (
        <div
          role="status"
          aria-live="polite"
          className="pointer-events-none fixed bottom-6 right-6 z-40 w-[360px] max-w-[calc(100vw-2rem)] max-md:bottom-auto max-md:left-3 max-md:right-3 max-md:top-16 max-md:w-auto"
        >
          <div className="pointer-events-auto rounded-2xl border border-[var(--border)] bg-[var(--card)]/95 p-4 shadow-xl backdrop-blur-md">
            <div className="flex items-start gap-3">
              <span
                className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${
                  showFailed
                    ? "bg-red-500/10 text-red-600 dark:text-red-400"
                    : "bg-sky-500/10 text-sky-700 dark:text-sky-300"
                }`}
              >
                {activeJob ? (
                  <RotateCw className="h-4 w-4 animate-spin" />
                ) : showFailed ? (
                  <CircleAlert className="h-4 w-4" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
              </span>

              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[13px] font-semibold text-[var(--foreground)]">
                      {activeJob
                        ? t("Updating DeepTutor…")
                        : showFailed
                          ? t("updateJob.failed")
                          : t("Update available")}
                    </p>
                    <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                      {activeJob
                        ? t(`updateJob.${activeJob.status}`)
                        : showFailed
                          ? (job?.error || t("Retry from Settings → About."))
                          : t("DeepTutor {{version}} is available.", { version })}
                    </p>
                  </div>
                  {showUpdate && (
                    <button
                      type="button"
                      onClick={dismiss}
                      aria-label={t("Dismiss")}
                      className="rounded p-0.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>

                {activeJob ? (
                  <div className="mt-3 h-1 overflow-hidden rounded-full bg-[var(--accent)]">
                    <span className="block h-full w-1/3 animate-pulse rounded-full bg-sky-500" />
                  </div>
                ) : showFailed ? (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    {canUpdate && (
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => setConfirmOpen(true)}
                        icon={<Download className="h-3.5 w-3.5" />}
                      >
                        {t("Retry")}
                      </Button>
                    )}
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={dismissFailedJob}
                    >
                      {t("Dismiss")}
                    </Button>
                  </div>
                ) : (
                  <>
                    {status?.release?.excerpt && (
                      <p className="mt-2 line-clamp-3 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                        {status.release.excerpt}
                      </p>
                    )}
                    <p className="mt-2 text-[11.5px] text-[var(--muted-foreground)]">
                      {t("You are running {{version}}.", {
                        version: status?.current_version ?? "",
                      })}
                    </p>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      {canUpdate ? (
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => setConfirmOpen(true)}
                          icon={<Download className="h-3.5 w-3.5" />}
                        >
                          {t("Update to {{version}}", { version })}
                        </Button>
                      ) : status?.is_admin ? (
                        <Link
                          href="/settings/about"
                          className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--accent)]"
                        >
                          {t("Update instructions")}
                          <ArrowUpRight className="h-3.5 w-3.5" />
                        </Link>
                      ) : (
                        <span className="text-[11.5px] text-[var(--muted-foreground)]">
                          {t("Ask an administrator to update DeepTutor.")}
                        </span>
                      )}
                      {status?.release?.url && (
                        <a
                          href={status.release.url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="inline-flex items-center gap-1 px-1.5 py-1 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                        >
                          {t("Release notes")}
                          <ArrowUpRight className="h-3.5 w-3.5" />
                        </a>
                      )}
                    </div>
                    {actionError && (
                      <p className="mt-2 text-[11.5px] text-red-600 dark:text-red-400">
                        {actionError}
                      </p>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirmOpen}
        title={t("Update and restart DeepTutor?")}
        confirmLabel={t("Update and restart")}
        busy={requesting}
        busyLabel={t("Preparing update…")}
        onConfirm={() => void update()}
        onCancel={() => setConfirmOpen(false)}
      >
        {t(
          "DeepTutor will briefly stop, install {{version}}, and reopen with the same settings. Active conversations must finish first.",
          { version },
        )}
      </ConfirmDialog>

      {whatsNew && (
        <div
          className="fixed inset-0 z-[210] flex items-center justify-center bg-[var(--overlay)] px-4"
          role="dialog"
          aria-modal="true"
          aria-label={t("What's new in {{version}}", {
            version: whatsNew.version,
          })}
          onClick={() => setWhatsNew(null)}
        >
          <div
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-xl"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
                  <Sparkles className="h-4 w-4" />
                </span>
                <div>
                  <h2 className="text-base font-semibold text-[var(--foreground)]">
                    {t("What's new in {{version}}", {
                      version: whatsNew.version,
                    })}
                  </h2>
                  <p className="mt-0.5 flex items-center gap-1 text-[12px] text-emerald-700 dark:text-emerald-300">
                    <Check className="h-3.5 w-3.5" />
                    {t("updateJob.succeeded")}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setWhatsNew(null)}
                aria-label={t("Close")}
                className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="mt-4 max-h-[50vh] overflow-y-auto whitespace-pre-line text-[13px] leading-6 text-[var(--muted-foreground)]">
              {whatsNew.excerpt}
            </p>
            <div className="mt-5 flex items-center justify-end gap-2">
              {whatsNew.url && (
                <a
                  href={whatsNew.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
                >
                  {t("Release notes")}
                  <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
              )}
              <Button type="button" size="sm" onClick={() => setWhatsNew(null)}>
                {t("Close")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
