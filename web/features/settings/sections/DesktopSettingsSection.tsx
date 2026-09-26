"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, FolderOpen, RefreshCw, RotateCcw } from "lucide-react";

import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
} from "@/components/settings/shared";
import {
  SHELL_EVENTS,
  checkUpdates,
  installShellUpdate,
  isDesktopShell,
  onShellEvent,
  openShellLogs,
  restartApp,
  restartLocalService,
  shellSettings,
  shellStatus,
  updateShellSettings,
  type DesktopShellStatus,
  type ShellSettingsSnapshot,
  type ShellSettingsPatch,
  type UpdateReport,
} from "@/lib/desktop-shell";

/**
 * Desktop-shell preferences.
 *
 * Everything here belongs to the **shell**, not to the web app: whether closing
 * the window hides to the tray, whether finished rounds raise a system
 * notification, which runtime pack is installed, where the logs live. The page
 * is reachable from the menu bar (`⌘,`) and from the settings hub, and it
 * degrades to an explanation when the same build is opened in a browser.
 */
export default function DesktopSettingsPage() {
  const { t } = useTranslation();
  const [available, setAvailable] = useState(false);
  const [settings, setSettings] = useState<ShellSettingsSnapshot | null>(null);
  const [status, setStatus] = useState<DesktopShellStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Latest shell-channel answer, so the page can offer the install button. */
  const [shellUpdate, setShellUpdate] = useState<UpdateReport["shell"] | null>(
    null,
  );

  const refresh = useCallback(async () => {
    if (!isDesktopShell()) {
      setAvailable(false);
      return;
    }
    setAvailable(true);
    try {
      const [nextSettings, nextStatus] = await Promise.all([
        shellSettings(),
        shellStatus(),
      ]);
      setSettings(nextSettings);
      setStatus(nextStatus);
    } catch (cause) {
      setError(String(cause));
    }
  }, []);

  useEffect(() => {
    void refresh();
    // The menu bar can flip the same two preferences; follow it instead of
    // showing a stale checkbox until the next navigation.
    return onShellEvent<ShellSettingsSnapshot>(
      SHELL_EVENTS.shellSettings,
      (payload) => {
        setSettings(payload);
      },
    );
  }, [refresh]);

  const apply = useCallback(
    (action: string, patch: ShellSettingsPatch) => {
      setBusy(action);
      setError(null);
      setMessage(null);
      void updateShellSettings(patch)
        .then(setSettings)
        .catch((cause: unknown) => setError(String(cause)))
        .finally(() => setBusy(null));
    },
    [],
  );

  const run = useCallback(async (action: string, work: () => Promise<void>) => {
    setBusy(action);
    setError(null);
    setMessage(null);
    try {
      await work();
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(null);
    }
  }, []);

  if (!available) {
    return (
      <div data-tour="tour-desktop">
        <SettingsPageHeader
          title={t("Desktop app")}
          description={t("Preferences owned by the DeepTutor desktop shell.")}
        />
        <SettingSection title={t("Desktop app")}>
          <p className="py-3.5 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "These settings belong to the DeepTutor desktop app. You are using DeepTutor in a browser, so there is nothing to configure here.",
            )}
          </p>
        </SettingSection>
      </div>
    );
  }

  return (
    <div data-tour="tour-desktop">
      <SettingsPageHeader
        title={t("Desktop app")}
        description={t(
          "Window behaviour, notifications and the local runtime the desktop app supervises.",
        )}
      />

      <SettingSection
        title={t("Window")}
        description={t("How the app behaves when you are done with it.")}
      >
        <SettingRow
          title={t("Hide to the tray when the window closes")}
          description={t(
            "Closing the window keeps the app and its running tasks alive. Quit from the tray menu or with ⌘Q.",
          )}
          control={
            <input
              type="checkbox"
              aria-label={t("Hide to the tray when the window closes")}
              checked={Boolean(settings?.close_to_tray)}
              disabled={busy !== null}
              onChange={(event) =>
                apply("close_to_tray", {
                  close_to_tray: event.target.checked,
                })
              }
            />
          }
        />
        <SettingRow
          title={t("Notify me when a round finishes")}
          description={t(
            "A system notification when a turn completes while the window is in the background. Clicking it returns to that conversation.",
          )}
          control={
            <input
              type="checkbox"
              aria-label={t("Notify me when a round finishes")}
              checked={Boolean(settings?.notifications)}
              disabled={busy !== null}
              onChange={(event) =>
                apply("notifications", {
                  notifications: event.target.checked,
                })
              }
            />
          }
        />
      </SettingSection>

      <SettingSection
        title={t("Local service")}
        description={t("The Python backend and the web server the window shows.")}
      >
        <SettingRow
          title={t("Status")}
          description={status?.message}
          control={
            <span className="font-mono text-[11.5px] text-[var(--muted-foreground)]">
              {status?.launcher_running
                ? `${t("Running")} · pid ${status.launcher_pid ?? "-"}`
                : t("Stopped")}
            </span>
          }
        />
        <SettingRow
          title={t("Runtime")}
          description={
            status?.pack
              ? `${t("Runtime pack")}: ${status.pack}`
              : t("Running from a local environment")
          }
          control={
            <span className="font-mono text-[11.5px] text-[var(--muted-foreground)]">
              {status?.python ? status.python.split("/").pop() : ""}
            </span>
          }
        />
        <SettingRow
          title={t("Data directory")}
          description={status?.home}
          control={
            settings?.restart_required ? (
              <span className="text-[11.5px] text-[var(--muted-foreground)]">
                {t("Restart required")}
              </span>
            ) : null
          }
        />
        <div className="flex flex-wrap gap-2 pt-3.5">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-xs disabled:opacity-50"
            disabled={busy !== null}
            onClick={() =>
              void run("restart", async () => {
                await restartLocalService();
                setMessage(t("Local service restarted."));
                await refresh();
              })
            }
          >
            <RotateCcw size={14} /> {t("Restart local service")}
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-xs disabled:opacity-50"
            disabled={busy !== null}
            onClick={() => void run("logs", () => openShellLogs(status))}
          >
            <FolderOpen size={14} /> {t("Open log folder")}
          </button>
        </div>
      </SettingSection>

      <SettingSection
        title={t("Updates")}
        description={t(
          "The desktop app ships as two layers: the shell (this window) and the local runtime pack (Python, Node and the web bundle). They update separately.",
        )}
      >
        <div className="pt-3.5">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-xs disabled:opacity-50"
            disabled={busy !== null}
            onClick={() =>
              void run("updates", async () => {
                const report = await checkUpdates();
                setShellUpdate(report.shell);
                setMessage(`${report.runtime.detail}；${report.shell.detail}`);
                await refresh();
              })
            }
          >
            <RefreshCw size={14} /> {t("Check for updates")}
          </button>
          {/*
            The runtime plane is a separate, explicit action: the shell asks for
            a native confirmation and only then downloads and installs the pack,
            so the "check" button above never installs anything by itself.
          */}
          <button
            type="button"
            className="ml-2 inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-xs disabled:opacity-50"
            disabled={busy !== null}
            onClick={() =>
              void run("runtime", async () => {
                const report = await checkUpdates({ install: true });
                setShellUpdate(report.shell);
                setMessage(report.runtime.detail);
                await refresh();
              })
            }
          >
            <Download size={14} /> {t("Install runtime update")}
          </button>
          {shellUpdate?.status === "available" && (
            <button
              type="button"
              className="ml-2 inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-2 text-xs text-[var(--background)] disabled:opacity-50"
              disabled={busy !== null}
              onClick={() =>
                void run("install", async () => {
                  const result = await installShellUpdate();
                  setMessage(result.detail);
                  // The new build only runs after a relaunch; the installer has
                  // already replaced the bundle by the time we get here.
                  await restartApp();
                })
              }
            >
              <Download size={14} />
              {t("Download and install {{version}}", {
                version: shellUpdate.available_version ?? "",
              })}
            </button>
          )}
        </div>
        {shellUpdate && (
          <p className="pt-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {shellUpdate.detail}
          </p>
        )}
      </SettingSection>

      {message && (
        <p
          aria-live="polite"
          className="mt-3 text-[12.5px] text-[var(--muted-foreground)]"
        >
          {message}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-3 text-[12.5px] text-[var(--destructive)]">
          {error}
        </p>
      )}
    </div>
  );
}
