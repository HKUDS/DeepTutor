"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, RefreshCw, ShieldCheck, Unplug } from "lucide-react";
import { useTranslation } from "react-i18next";

import Button from "@/components/ui/Button";
import {
  buildSshForwardCommand,
  cancelCodexLogin,
  codexRemoteGuidance,
  CodexOAuthApiError,
  codexErrorMessageKey,
  codexStatusMessageKey,
  getCodexStatus,
  isLoopbackHostname,
  logoutCodex,
  refreshCodexModels,
  shouldPollCodexStatus,
  startCodexLogin,
  type CodexLoginStart,
  type CodexOAuthStatus,
} from "@/lib/codex-oauth";

import { useSettings } from "./SettingsContext";

export function CodexOAuthCard() {
  const { t } = useTranslation();
  const { reloadSettings, hasUnsavedChanges, setToast } = useSettings();
  const [status, setStatus] = useState<CodexOAuthStatus | null>(null);
  const [pending, setPending] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [pollTick, setPollTick] = useState(0);
  const [loginStart, setLoginStart] = useState<CodexLoginStart | null>(null);
  const reloadedOperation = useRef<string | null>(null);
  const statusRequestSequence = useRef(0);
  const remoteAccess =
    typeof window !== "undefined" &&
    !isLoopbackHostname(window.location.hostname);

  const recordStatus = useCallback((nextStatus: CodexOAuthStatus) => {
    setStatus(nextStatus);
    const terminalOperation =
      nextStatus.operation_state === "completed" ||
      nextStatus.operation_state === "cancelled" ||
      nextStatus.operation_state === "expired" ||
      nextStatus.operation_state === "failed";
    if (!terminalOperation) return;
    setLoginStart((loginStart) =>
      loginStart && nextStatus.operation_id === loginStart.operation_id
        ? null
        : loginStart,
    );
  }, []);

  const invalidateStatusRequests = useCallback(() => {
    statusRequestSequence.current += 1;
  }, []);

  const loadStatus = useCallback(
    async (shouldApply: () => boolean = () => true) => {
      statusRequestSequence.current += 1;
      const requestSequence = statusRequestSequence.current;
      try {
        const next = await getCodexStatus();
        if (
          requestSequence !== statusRequestSequence.current ||
          !shouldApply()
        ) {
          return null;
        }
        recordStatus(next);
        setErrorKey(null);
        return next;
      } catch (error) {
        if (
          requestSequence !== statusRequestSequence.current ||
          !shouldApply()
        ) {
          return null;
        }
        setErrorKey(
          codexErrorMessageKey(
            error instanceof CodexOAuthApiError ? error.code : null,
          ),
        );
        return null;
      }
    },
    [recordStatus],
  );

  useEffect(() => {
    let cancelled = false;
    void loadStatus(() => !cancelled);
    return () => {
      cancelled = true;
      invalidateStatusRequests();
    };
  }, [invalidateStatusRequests, loadStatus]);

  useEffect(() => {
    if (pending || !status || !shouldPollCodexStatus(status)) return;
    // pollTick, not the status object, is what schedules the next poll: a failed
    // request leaves `status` identical, and keying the timer off it alone would
    // strand the card on "waiting" forever after one dropped response.
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void (async () => {
        await loadStatus(() => !cancelled);
        if (!cancelled) setPollTick((tick) => tick + 1);
      })();
    }, 1_000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [loadStatus, pending, status, pollTick]);

  // Reloading replaces the whole catalog draft, so this must never run behind
  // the operator's back while they have unsaved edits open on another provider.
  const syncCatalog = useCallback(async () => {
    if (hasUnsavedChanges) {
      setToast(t("codex.oauth.reloadDeferred"));
      return;
    }
    await reloadSettings();
  }, [hasUnsavedChanges, reloadSettings, setToast, t]);

  useEffect(() => {
    if (
      status?.operation_state !== "completed" ||
      !status.operation_id ||
      reloadedOperation.current === status.operation_id
    ) {
      return;
    }
    reloadedOperation.current = status.operation_id;
    void syncCatalog();
  }, [syncCatalog, status]);

  const localSignIn = async () => {
    invalidateStatusRequests();
    const authWindow = window.open("about:blank", "_blank", "popup");
    if (authWindow) authWindow.opener = null;
    setPending(true);
    setErrorKey(null);
    try {
      const started = await startCodexLogin();
      if (authWindow) {
        authWindow.location.replace(started.authorize_url);
      } else {
        window.location.assign(started.authorize_url);
      }
      await loadStatus();
    } catch (error) {
      authWindow?.close();
      setErrorKey(
        codexErrorMessageKey(
          error instanceof CodexOAuthApiError ? error.code : null,
        ),
      );
    } finally {
      setPending(false);
    }
  };

  const remoteSignIn = async () => {
    invalidateStatusRequests();
    setPending(true);
    setErrorKey(null);
    try {
      const started = await startCodexLogin();
      setLoginStart(started);
      await loadStatus();
    } catch (error) {
      setErrorKey(
        codexErrorMessageKey(
          error instanceof CodexOAuthApiError ? error.code : null,
        ),
      );
    } finally {
      setPending(false);
    }
  };

  const signIn = remoteAccess ? remoteSignIn : localSignIn;

  const remoteGuidance = codexRemoteGuidance(status, loginStart);
  const sshCommand = remoteGuidance
    ? buildSshForwardCommand(
        remoteGuidance.callback_port,
        window.location.hostname,
        remoteGuidance.callback_forward_port,
      )
    : "";

  const copyCommand = async () => {
    if (!sshCommand) return;
    try {
      await navigator.clipboard.writeText(sshCommand);
      setToast(t("codex.oauth.commandCopied"));
    } catch {
      setToast(t("codex.oauth.copyFailed"));
    }
  };

  const openAuthorization = () => {
    if (!remoteGuidance) return;
    window.open(remoteGuidance.authorize_url, "_blank", "noopener");
  };

  const cancel = async () => {
    invalidateStatusRequests();
    setPending(true);
    try {
      const nextStatus = await cancelCodexLogin();
      invalidateStatusRequests();
      recordStatus(nextStatus);
    } catch (error) {
      setErrorKey(
        codexErrorMessageKey(
          error instanceof CodexOAuthApiError ? error.code : null,
        ),
      );
    } finally {
      setLoginStart(null);
      setPending(false);
    }
  };

  const refresh = async () => {
    invalidateStatusRequests();
    setPending(true);
    try {
      const nextStatus = await refreshCodexModels();
      invalidateStatusRequests();
      recordStatus(nextStatus);
      await syncCatalog();
      setErrorKey(null);
    } catch (error) {
      setErrorKey(
        codexErrorMessageKey(
          error instanceof CodexOAuthApiError ? error.code : null,
        ),
      );
    } finally {
      setPending(false);
    }
  };

  const logout = async () => {
    invalidateStatusRequests();
    setPending(true);
    try {
      const nextStatus = await logoutCodex();
      invalidateStatusRequests();
      recordStatus(nextStatus);
      setLoginStart(null);
      await syncCatalog();
      setErrorKey(null);
    } catch (error) {
      setErrorKey(
        codexErrorMessageKey(
          error instanceof CodexOAuthApiError ? error.code : null,
        ),
      );
    } finally {
      setPending(false);
    }
  };

  const polling = Boolean(status && shouldPollCodexStatus(status));
  const connected = status?.connection === "connected";
  const messageKey =
    errorKey || (status ? codexStatusMessageKey(status) : null);
  const callbackPort = status?.callback_port ?? loginStart?.callback_port;
  const displayMessageKey =
    messageKey === "codex.oauth.callbackMissing" && callbackPort == null
      ? "codex.oauth.callbackMissingUnknown"
      : messageKey;

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--muted)]/30 p-4">
      <div className="flex items-start gap-3">
        <ShieldCheck className="mt-0.5 h-5 w-5 text-[var(--primary)]" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{t("codex.oauth.title")}</p>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            {t("codex.oauth.isolated")}
          </p>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            {t("codex.oauth.ownerBound")}
          </p>
          {!connected && (
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              {t("codex.oauth.localOnly")}
            </p>
          )}
          <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
            {t("codex.oauth.experimental")}
          </p>
          {displayMessageKey && (
            <p className="mt-3 text-sm text-[var(--foreground)]">
              {t(displayMessageKey, {
                port: callbackPort,
              })}
            </p>
          )}
          {connected && status?.model_count !== undefined && (
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              {t("codex.oauth.modelCount", { count: status.model_count })}
            </p>
          )}
          {remoteAccess && remoteGuidance && (
            <div className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
              <p className="text-sm font-medium">
                {t("codex.oauth.remoteTitle")}
              </p>
              <p className="mt-2 text-xs text-[var(--muted-foreground)]">
                {t("codex.oauth.remoteSteps")}
              </p>
              <p className="mt-3 text-xs font-medium">
                {t("codex.oauth.callbackAddress")}
              </p>
              <code className="mt-1 block break-all text-xs">
                {remoteGuidance.redirect_uri}
              </code>
              <p className="mt-2 text-xs text-[var(--muted-foreground)]">
                {t("codex.oauth.expiresIn", {
                  seconds: remoteGuidance.expires_in,
                })}
              </p>
              <pre className="mt-3 overflow-x-auto rounded-md bg-[var(--muted)] p-2 text-xs">
                <code>{sshCommand}</code>
              </pre>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => void copyCommand()}
                >
                  {t("codex.oauth.copyCommand")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  onClick={openAuthorization}
                  icon={<ExternalLink className="h-4 w-4" />}
                >
                  {t("codex.oauth.openAuthorization")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={pending}
                  onClick={() => void cancel()}
                >
                  {t("codex.oauth.cancel")}
                </Button>
              </div>
            </div>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            {!connected && !polling && (
              <Button
                type="button"
                size="sm"
                loading={pending}
                onClick={() => void signIn()}
                icon={<ExternalLink className="h-4 w-4" />}
              >
                {t("codex.oauth.signIn")}
              </Button>
            )}
            {polling && !(remoteAccess && remoteGuidance) && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={pending}
                onClick={() => void cancel()}
              >
                {t("codex.oauth.cancel")}
              </Button>
            )}
            {connected && (
              <>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  loading={pending}
                  onClick={() => void refresh()}
                  icon={<RefreshCw className="h-4 w-4" />}
                >
                  {t("codex.oauth.refresh")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="danger"
                  disabled={pending}
                  onClick={() => void logout()}
                  icon={<Unplug className="h-4 w-4" />}
                >
                  {t("codex.oauth.logout")}
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
