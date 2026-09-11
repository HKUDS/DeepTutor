"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, RefreshCw, ShieldCheck, Unplug } from "lucide-react";
import { useTranslation } from "react-i18next";

import Button from "@/components/ui/Button";
import { invalidateLLMOptionsCache } from "@/lib/llm-options";
import { reasoningEffortOptionsFromSupportedLevels } from "@/lib/reasoning-effort";
import {
  buildSshForwardCommand,
  cancelCodexLogin,
  codexRemoteGuidance,
  CodexOAuthApiError,
  codexErrorMessageKey,
  codexStatusMessageKey,
  completeCodexLogin,
  getCodexStatus,
  isLoopbackHostname,
  logoutCodex,
  refreshCodexModels,
  shouldPollCodexStatus,
  startCodexLogin,
  setCodexReasoningEffort,
  type CodexLoginStart,
  type CodexOAuthStatus,
  type CodexReasoningModel,
} from "@/lib/codex-oauth";

import { useSettings } from "@/features/settings/store/SettingsStore";

export function CodexOAuthCard() {
  const { t } = useTranslation();
  const { catalogEditable, reloadSettings, hasUnsavedChanges, setToast } =
    useSettings();
  const [status, setStatus] = useState<CodexOAuthStatus | null>(null);
  const [pending, setPending] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [pollTick, setPollTick] = useState(0);
  const [loginStart, setLoginStart] = useState<CodexLoginStart | null>(null);
  // Cleared on submit and when the waiting operation ends, so a callback
  // address never outlives the login it belongs to.
  const [callbackUrl, setCallbackUrl] = useState("");
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
    setCallbackUrl("");
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
    // Every model picker reads a cached option list — derived from the catalog
    // for an administrator, from /settings/llm-options for an ordinary user —
    // and a sign-in, logout, or model refresh changes what belongs in it. Drop
    // the cache first, and unconditionally: the server has already changed
    // even when the catalog reload below is deferred.
    invalidateLLMOptionsCache();
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

  const updateReasoningEffort = async (
    model: CodexReasoningModel,
    value: string,
  ) => {
    invalidateStatusRequests();
    setPending(true);
    try {
      const nextStatus = await setCodexReasoningEffort(
        model.model,
        value || null,
      );
      invalidateStatusRequests();
      recordStatus(nextStatus);
      setErrorKey(null);
      setToast(t("codex.oauth.reasoningSaved"));
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

  const submitCallbackUrl = async () => {
    const pasted = callbackUrl.trim();
    if (!pasted) return;
    invalidateStatusRequests();
    setPending(true);
    setErrorKey(null);
    try {
      const nextStatus = await completeCodexLogin(pasted);
      recordStatus(nextStatus);
      setCallbackUrl("");
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
          {connected &&
            catalogEditable === false &&
            status.models.length > 0 && (
              <div className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
                <p className="text-sm font-medium">
                  {t("codex.oauth.reasoningTitle")}
                </p>
                <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                  {t("codex.oauth.reasoningDescription")}
                </p>
                <div className="mt-3 space-y-3">
                  {status.models.map((model) => {
                    const options = reasoningEffortOptionsFromSupportedLevels(
                      model.supported_reasoning_levels,
                    );
                    if (options.length === 0) return null;
                    return (
                      <label key={model.model} className="block">
                        <span className="mb-1 block truncate text-xs font-medium">
                          {model.name}
                        </span>
                        <select
                          className="h-9 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 text-sm text-[var(--foreground)] outline-none focus:border-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-60"
                          value={model.reasoning_effort || ""}
                          disabled={pending}
                          onChange={(event) =>
                            void updateReasoningEffort(
                              model,
                              event.target.value,
                            )
                          }
                        >
                          {options.map((option) => (
                            <option
                              key={option.value || "auto"}
                              value={option.value}
                            >
                              {t(option.label)}
                            </option>
                          ))}
                        </select>
                      </label>
                    );
                  })}
                </div>
              </div>
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
          {remoteGuidance && (
            <div className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
              <p className="text-sm font-medium">
                {t("codex.oauth.callbackRecoveryTitle")}
              </p>
              <p className="mt-2 text-xs text-[var(--muted-foreground)]">
                {t("codex.oauth.callbackRecoveryHint")}
              </p>
              <label
                className="mt-3 block text-xs font-medium"
                htmlFor="codex-callback-url"
              >
                {t("codex.oauth.callbackUrlLabel")}
              </label>
              <input
                id="codex-callback-url"
                type="url"
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
                value={callbackUrl}
                onChange={(event) => setCallbackUrl(event.target.value)}
                placeholder={remoteGuidance.redirect_uri}
                className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1.5 text-xs"
              />
              <div className="mt-3">
                <Button
                  type="button"
                  size="sm"
                  loading={pending}
                  disabled={!callbackUrl.trim()}
                  onClick={() => void submitCallbackUrl()}
                >
                  {t("codex.oauth.completeSignIn")}
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
