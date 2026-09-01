"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  Download,
  Github,
  RefreshCw,
  RotateCw,
  ShieldCheck,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Toggle } from "@/components/settings/Toggle";
import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
} from "@/components/settings/shared";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import {
  checkAppUpdate,
  fetchAppUpdateJob,
  fetchAppUpdateStatus,
  requestAppUpdate,
  setAppUpdateChecks,
  updateJobIsActive,
  type AppUpdateStatus,
  type InstallMode,
  type UpdateJob,
  type UpdateJobStatus,
} from "@/lib/app-update";
import { normalizeVersionTag } from "@/lib/version";

const POLL_INTERVAL_MS = 800;
const POLL_TIMEOUT_MS = 120_000;

const INSTALLATION_LABELS: Record<InstallMode, string> = {
  pypi: "PyPI package",
  source: "Source checkout",
  docker: "Docker container",
  unknown: "Unknown installation",
};

function jobTone(status: UpdateJobStatus) {
  if (status === "failed") return "text-red-600 dark:text-red-400";
  if (status === "succeeded") return "text-emerald-700 dark:text-emerald-400";
  return "text-sky-700 dark:text-sky-400";
}

export default function AboutSettingsPage() {
  const { t, i18n } = useTranslation();
  const [status, setStatus] = useState<AppUpdateStatus | null>(null);
  const [job, setJob] = useState<UpdateJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [savingChecks, setSavingChecks] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const next = await fetchAppUpdateStatus();
      setStatus(next);
      setJob(next.job);
      setError(next.check_error || "");
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : (t("Unable to load version information.") as string),
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const activeJob = Boolean(job && updateJobIsActive(job.status));
  useEffect(() => {
    if (!activeJob) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = Date.now() + POLL_TIMEOUT_MS;

    const poll = async () => {
      try {
        const next = await fetchAppUpdateJob();
        if (cancelled) return;
        if (next) {
          setJob(next);
          if (!updateJobIsActive(next.status)) {
            if (next.status === "succeeded") await load();
            return;
          }
        }
      } catch {
        // The backend is expected to disappear while the launcher updates and
        // restarts it. Keep polling until it reconnects or the deadline passes.
      }
      if (cancelled) return;
      if (Date.now() >= deadline) {
        setError(t("DeepTutor did not reconnect before the update timeout."));
        return;
      }
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [activeJob, load, t]);

  const check = useCallback(async () => {
    setChecking(true);
    setError("");
    try {
      const next = await checkAppUpdate();
      setStatus(next);
      setJob(next.job);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : (t("Unable to check for updates.") as string),
      );
    } finally {
      setChecking(false);
    }
  }, [t]);

  const changeChecks = useCallback(
    async (enabled: boolean) => {
      setSavingChecks(true);
      setError("");
      try {
        const next = await setAppUpdateChecks(enabled);
        setStatus(next);
        setJob(next.job);
      } catch (cause) {
        setError(
          cause instanceof Error
            ? cause.message
            : (t("Unable to save update settings.") as string),
        );
      } finally {
        setSavingChecks(false);
      }
    },
    [t],
  );

  const update = useCallback(async () => {
    setRequesting(true);
    setError("");
    try {
      const next = await requestAppUpdate();
      setJob(next);
      setConfirmOpen(false);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : (t("Unable to start the update.") as string),
      );
    } finally {
      setRequesting(false);
    }
  }, [t]);

  const currentVersion =
    normalizeVersionTag(status?.current_version) ??
    normalizeVersionTag(process.env.NEXT_PUBLIC_APP_VERSION) ??
    "—";
  const latestVersion = normalizeVersionTag(status?.release?.version);
  const checkedAt = useMemo(() => {
    if (!status?.checked_at) return "";
    const parsed = new Date(status.checked_at);
    if (Number.isNaN(parsed.getTime())) return "";
    return parsed.toLocaleString(
      i18n.language?.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US",
      { dateStyle: "medium", timeStyle: "short" },
    );
  }, [i18n.language, status?.checked_at]);

  const installMode = status?.installation.mode ?? "unknown";
  const canUpdate = Boolean(
    status?.is_admin &&
    status.check_enabled &&
    status.update_available &&
    status.installation.automatic_update &&
    status.launcher_managed &&
    !activeJob,
  );
  const upToDate = Boolean(status?.release && !status.update_available);

  return (
    <div data-tour="tour-about" className="pb-8">
      <SettingsPageHeader
        title={t("About")}
        description={t(
          "DeepTutor version, release channel, and the safest update path for this installation.",
        )}
      />

      <section className="relative mb-10 overflow-hidden border-y border-[var(--border)]/60 py-7">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-12 -top-16 h-40 w-40 rounded-full border-[28px] border-[var(--foreground)]/[0.025]"
        />
        <div className="relative flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              {t("Running version")}
            </div>
            <div className="font-serif text-[38px] font-semibold leading-none tracking-[-0.035em] text-[var(--foreground)]">
              {currentVersion}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {status?.release?.url && (
              <a
                href={status.release.url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
              >
                {t("Release notes")}
                <ArrowUpRight className="h-3.5 w-3.5" />
              </a>
            )}
            {status?.is_admin && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                loading={checking}
                disabled={!status.check_enabled || activeJob}
                icon={<RefreshCw className="h-3.5 w-3.5" />}
                onClick={() => void check()}
              >
                {t("Check now")}
              </Button>
            )}
            {canUpdate && (
              <Button
                type="button"
                size="sm"
                icon={<Download className="h-3.5 w-3.5" />}
                onClick={() => setConfirmOpen(true)}
              >
                {t("Update to {{version}}", { version: latestVersion ?? "" })}
              </Button>
            )}
          </div>
        </div>
      </section>

      {error && (
        <div className="mb-7 flex items-start gap-2 border-l-2 border-red-500/70 py-1 pl-3 text-[12.5px] leading-relaxed text-red-600 dark:text-red-400">
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <SettingSection title={t("Software")}>
        <SettingRow
          title={t("Current version")}
          control={<CodeValue value={currentVersion} />}
        />
        <SettingRow
          title={t("Installation")}
          description={t(
            status?.installation.reason || "How DeepTutor is installed here.",
          )}
          control={
            <span className="text-[12.5px] text-[var(--foreground)]">
              {t(INSTALLATION_LABELS[installMode])}
            </span>
          }
        />
        <SettingRow
          title={t("Release channel")}
          description={t(
            "Only stable, published DeepTutor releases are considered.",
          )}
          control={
            <span className="text-[12.5px] text-[var(--foreground)]">
              {t("Stable")}
            </span>
          }
        />
      </SettingSection>

      <SettingSection
        title={t("Updates")}
        description={t(
          "Version checks are cached for 24 hours. DeepTutor never installs an update without confirmation.",
        )}
      >
        <SettingRow
          title={t("Check for updates")}
          description={t(
            "Turn this off for offline or controlled deployments.",
          )}
          control={
            status?.is_admin ? (
              <Toggle
                checked={status?.check_enabled ?? true}
                disabled={loading || savingChecks || activeJob}
                onChange={(enabled) => void changeChecks(enabled)}
              />
            ) : (
              <span className="text-[12.5px] text-[var(--muted-foreground)]">
                {status?.check_enabled ? t("On") : t("Off")}
              </span>
            )
          }
        />
        <SettingRow
          title={t("Latest stable release")}
          description={
            checkedAt
              ? t("Last checked {{time}}", { time: checkedAt })
              : status?.check_enabled
                ? t("Not checked yet")
                : t("Version checks are disabled.")
          }
          control={
            <div className="flex items-center gap-2">
              {upToDate && <Check className="h-3.5 w-3.5 text-emerald-500" />}
              <CodeValue value={latestVersion ?? "—"} />
            </div>
          }
        />

        {status?.release?.migration_warning && (
          <div className="flex items-start gap-2 border-t border-[var(--border)]/50 py-3.5 text-[12.5px] leading-relaxed text-amber-700 dark:text-amber-400">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
            {t(
              "This release mentions migrations or breaking changes. Read the release notes before updating.",
            )}
          </div>
        )}

        {status?.release?.excerpt && (
          <div className="border-t border-[var(--border)]/50 py-4">
            <div className="mb-2 text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--muted-foreground)]">
              {status.release.name || t("What changed")}
            </div>
            <p className="max-w-2xl whitespace-pre-line text-[12.5px] leading-6 text-[var(--muted-foreground)]">
              {status.release.excerpt}
            </p>
          </div>
        )}

        {status && !status.installation.automatic_update && (
          <div className="border-t border-[var(--border)]/50 py-4">
            <div className="mb-2 flex items-center gap-2 text-[12.5px] font-medium text-[var(--foreground)]">
              <ShieldCheck className="h-4 w-4 text-[var(--muted-foreground)]" />
              {t("Managed by your installation")}
            </div>
            <p className="mb-3 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
              {t(status.installation.reason)}
            </p>
            <code className="block overflow-x-auto rounded-lg bg-[var(--accent)]/60 px-3 py-2 text-[11.5px] text-[var(--foreground)]">
              {status.installation.command}
            </code>
          </div>
        )}

        {job && (
          <div
            className="border-t border-[var(--border)]/50 py-4"
            aria-live="polite"
          >
            <div
              className={`flex items-center gap-2 text-[12.5px] font-medium ${jobTone(job.status)}`}
            >
              {updateJobIsActive(job.status) ? (
                <RotateCw className="h-3.5 w-3.5 animate-spin" />
              ) : job.status === "succeeded" ? (
                <Check className="h-3.5 w-3.5" />
              ) : (
                <CircleAlert className="h-3.5 w-3.5" />
              )}
              {t(`updateJob.${job.status}`)}
            </div>
            {job.error && (
              <p className="mt-2 text-[12px] text-red-600 dark:text-red-400">
                {job.error}
              </p>
            )}
          </div>
        )}
      </SettingSection>

      <SettingSection title={t("Project")}>
        <ResourceRow
          title={t("GitHub")}
          description={t("Source code, issues, and contributions")}
          href="https://github.com/HKUDS/DeepTutor"
          icon={<Github className="h-4 w-4" />}
        />
        <ResourceRow
          title={t("Documentation")}
          description={t("Installation, configuration, and guides")}
          href="https://docs.deeptutor.info"
          icon={<ArrowUpRight className="h-4 w-4" />}
        />
      </SettingSection>

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
          { version: latestVersion ?? "" },
        )}
      </ConfirmDialog>
    </div>
  );
}

function CodeValue({ value }: { value: string }) {
  return (
    <code className="rounded-md bg-[var(--accent)]/60 px-2 py-1 text-[11.5px] tabular-nums text-[var(--foreground)]">
      {value}
    </code>
  );
}

function ResourceRow({
  title,
  description,
  href,
  icon,
}: {
  title: string;
  description: string;
  href: string;
  icon: React.ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="group flex items-center justify-between gap-5 border-t border-[var(--border)]/50 py-3.5 first:border-t-0"
    >
      <div>
        <div className="text-[13.5px] font-medium text-[var(--foreground)]">
          {title}
        </div>
        <p className="mt-1 text-[12px] text-[var(--muted-foreground)]">
          {description}
        </p>
      </div>
      <span className="text-[var(--muted-foreground)] transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-[var(--foreground)]">
        {icon}
      </span>
    </a>
  );
}
