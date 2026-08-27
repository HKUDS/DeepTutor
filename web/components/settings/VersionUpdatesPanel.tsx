"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUpCircle, ExternalLink, RefreshCw, X } from "lucide-react";

import Button from "@/components/ui/Button";
import { Toggle } from "@/components/settings/Toggle";
import {
  cancelVersionUpdate,
  checkVersionUpdates,
  getVersionStatus,
  getVersionUpdateStatus,
  isUpdateAvailable,
  startVersionUpdate,
  updateVersionCheckSettings,
  type VersionStatus,
} from "@/lib/version-check";
import { normalizeVersionTag } from "@/lib/version";

const INSTALL_MODE_LABELS: Record<string, string> = {
  pypi: "PyPI package",
  source: "Source checkout",
  docker: "Docker container",
  unknown: "Unknown installation",
};

export default function VersionUpdatesPanel() {
  const { t, i18n } = useTranslation();
  const [status, setStatus] = useState<VersionStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [savingSetting, setSavingSetting] = useState(false);
  const [startingUpdate, setStartingUpdate] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");
  const [updateError, setUpdateError] = useState("");

  useEffect(() => {
    let cancelled = false;
    getVersionStatus()
      .then((result) => {
        if (!cancelled) setStatus(result);
      })
      .catch(() => {
        if (!cancelled) setError(t("Unable to load version status"));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const updateState = status?.update.state ?? "idle";

  useEffect(() => {
    if (updateState !== "running") return;
    const timer = window.setInterval(() => {
      getVersionUpdateStatus()
        .then((next) => setStatus(next))
        .catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [updateState]);

  const check = useCallback(async () => {
    setChecking(true);
    setError("");
    try {
      setStatus(await checkVersionUpdates(true));
    } catch {
      setError(t("Unable to check for updates"));
    } finally {
      setChecking(false);
    }
  }, [t]);

  const changeCheckEnabled = useCallback(
    async (enabled: boolean) => {
      setSavingSetting(true);
      setError("");
      try {
        setStatus(await updateVersionCheckSettings(enabled));
      } catch {
        setError(t("Unable to save version settings"));
      } finally {
        setSavingSetting(false);
      }
    },
    [t],
  );

  const update = useCallback(async () => {
    setStartingUpdate(true);
    setUpdateError("");
    try {
      setStatus(await startVersionUpdate());
    } catch {
      setUpdateError(t("Unable to start the update"));
    } finally {
      setStartingUpdate(false);
    }
  }, [t]);

  const cancelUpdate = useCallback(async () => {
    setCancelling(true);
    setUpdateError("");
    try {
      setStatus(await cancelVersionUpdate());
    } catch {
      setUpdateError(t("Unable to cancel the update"));
    } finally {
      setCancelling(false);
    }
  }, [t]);

  const checkEnabled = status?.check_enabled ?? true;
  const currentTag =
    normalizeVersionTag(status?.current_version) ??
    normalizeVersionTag(process.env.NEXT_PUBLIC_APP_VERSION) ??
    "unknown";
  const latest = status?.latest_release ?? null;
  const latestTag = normalizeVersionTag(latest?.tag_name);
  const installation = status?.installation;
  const updateStatus = status?.update;
  const updateAvailable = checkEnabled && isUpdateAvailable(latest, status?.current_version);
  const checkedAt = status?.checked_at ? new Date(status.checked_at) : null;
  const checkedLabel = checkedAt
    ? checkedAt.toLocaleString(
        i18n.language?.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US",
        {
          dateStyle: "medium",
          timeStyle: "short",
        },
      )
    : null;
  const installMode = installation
    ? t(INSTALL_MODE_LABELS[installation.mode] ?? "Unknown installation")
    : "";

  return (
    <section
      data-tour="tour-version-updates"
      className="mt-4 rounded-2xl border border-[var(--border)]/70 bg-[var(--card)]/50"
      aria-label={t("Version & updates")}
    >
      <div className="flex flex-col gap-4 px-5 py-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <h2 className="text-[13px] font-medium tracking-tight text-[var(--foreground)]">
              {t("Version & updates")}
            </h2>
            {installMode && (
              <span className="rounded-full border border-[var(--border)]/60 px-2 py-0.5 text-[11px] text-[var(--muted-foreground)]">
                {installMode}
              </span>
            )}
          </div>
          <dl className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[12px]">
            <div className="flex items-baseline gap-2">
              <dt className="text-[var(--muted-foreground)]">{t("Current version")}</dt>
              <dd className="font-mono tabular-nums text-[var(--foreground)]">{currentTag}</dd>
            </div>
            <div className="flex items-baseline gap-2">
              <dt className="text-[var(--muted-foreground)]">{t("Latest release")}</dt>
              <dd className="font-mono tabular-nums text-[var(--foreground)]">
                {checkEnabled ? latestTag ?? t("Not checked yet") : t("Disabled")}
              </dd>
            </div>
          </dl>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <div className="flex items-center gap-2 pr-1">
            <span className="text-[12px] text-[var(--muted-foreground)]">
              {t("Check for updates")}
            </span>
            <Toggle
              checked={checkEnabled}
              disabled={savingSetting}
              onChange={changeCheckEnabled}
            />
          </div>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            loading={checking}
            disabled={!checkEnabled || updateState === "running"}
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={check}
          >
            {t("Check now")}
          </Button>
          {installation?.update_supported && (
            <Button
              type="button"
              size="sm"
              loading={startingUpdate || updateState === "running"}
              disabled={!updateAvailable}
              icon={<ArrowUpCircle className="h-3.5 w-3.5" />}
              onClick={update}
            >
              {t("Update now")}
            </Button>
          )}
          {updateState === "running" && (
            <button
              type="button"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border)]/60 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-40"
              aria-label={t("Cancel update")}
              disabled={cancelling}
              onClick={cancelUpdate}
            >
              <X className="h-4 w-4" />
            </button>
          )}
          {latest?.html_url && (
            <a
              href={latest.html_url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)]/60 px-3 py-1.5 text-xs font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--border)] hover:text-[var(--foreground)]"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              {t("View release")}
            </a>
          )}
        </div>
      </div>
      <div
        aria-live="polite"
        className="min-h-[72px] space-y-2 border-t border-[var(--border)]/50 px-5 py-3 text-[12px]"
      >
        {error && <p className="text-red-500">{error}</p>}
        {!checkEnabled ? (
          <p className="text-[var(--muted-foreground)]">
            {t("Version checks are disabled.")}
          </p>
        ) : latest ? (
          <div className="space-y-1.5">
            <p
              className={
                updateAvailable
                  ? "font-medium text-[var(--foreground)]"
                  : "text-[var(--muted-foreground)]"
              }
            >
              {updateAvailable ? t("Update available") : t("Up to date")}
              {checkedLabel ? ` - ${t("Checked {{time}}", { time: checkedLabel })}` : ""}
            </p>
            {latest.migration_bearing && (
              <p className="font-medium text-amber-600 dark:text-amber-400">
                {t("This release includes migration or breaking changes.")}
              </p>
            )}
            {latest.excerpt && (
              <p className="max-w-3xl whitespace-pre-line break-words leading-relaxed text-[var(--muted-foreground)]">
                {latest.excerpt}
              </p>
            )}
          </div>
        ) : (
          <p className="text-[var(--muted-foreground)]">{t("Not checked yet")}</p>
        )}

        {updateAvailable && installation && !installation.update_supported && (
          <p className="max-w-3xl text-[var(--muted-foreground)]">
            {installation.reason}{" "}
            <span className="font-mono">{installation.command}</span>
          </p>
        )}

        {updateStatus && updateStatus.state !== "idle" && (
          <div className="space-y-1.5">
            <p
              className={
                updateStatus.state === "failed"
                  ? "font-medium text-red-500"
                  : updateStatus.state === "done"
                    ? "font-medium text-emerald-600 dark:text-emerald-400"
                    : "text-[var(--muted-foreground)]"
              }
            >
              {updateStatus.message}
              {updateStatus.restart_required &&
                ` ${t("Previous version: {{version}}", {
                  version: updateStatus.previous_version,
                })}`}
            </p>
            {updateStatus.lines.length > 0 && (
              <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-[var(--border)]/60 px-3 py-2 font-mono text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                {updateStatus.lines.join("\n")}
              </pre>
            )}
          </div>
        )}
        {updateError && <p className="text-red-500">{updateError}</p>}
      </div>
    </section>
  );
}
