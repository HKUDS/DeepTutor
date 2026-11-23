"use client";

import Tooltip from "@/shared/ui/Tooltip";
import {
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  Loader2,
  LogIn,
  LogOut,
  RefreshCw,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  cancelGitHubCopilotLogin,
  getGitHubCopilotAuthStatus,
  logoutGitHubCopilot,
  shouldPollGitHubCopilotAuth,
  startGitHubCopilotLogin,
  type GitHubCopilotAuthStatus,
} from "@/lib/github-copilot-auth";

const POLL_INTERVAL_MS = 2000;

export function GitHubCopilotAuthCard({
  onAuthenticated,
}: {
  onAuthenticated?: () => void;
} = {}) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<GitHubCopilotAuthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [copied, setCopied] = useState(false);
  const [requestError, setRequestError] = useState("");
  const [pollNonce, setPollNonce] = useState(0);
  const mountedRef = useRef(true);
  const requestSeqRef = useRef(0);
  const pollAbortRef = useRef<AbortController | null>(null);
  const wasWaitingRef = useRef(false);
  const onAuthenticatedRef = useRef(onAuthenticated);
  onAuthenticatedRef.current = onAuthenticated;

  const isStale = useCallback(
    (seq: number) => !mountedRef.current || seq !== requestSeqRef.current,
    [],
  );

  const beginMutation = useCallback(() => {
    pollAbortRef.current?.abort();
    pollAbortRef.current = null;
    requestSeqRef.current += 1;
    return requestSeqRef.current;
  }, []);

  const applyStatus = useCallback((next: GitHubCopilotAuthStatus) => {
    const waitingNow = shouldPollGitHubCopilotAuth(next);
    if (wasWaitingRef.current && !waitingNow && next.connection === "connected") {
      wasWaitingRef.current = false;
      onAuthenticatedRef.current?.();
    } else {
      wasWaitingRef.current = waitingNow;
    }
    setStatus(next);
  }, []);

  const refresh = useCallback(async () => {
    const seq = beginMutation();
    const controller = new AbortController();
    pollAbortRef.current = controller;
    try {
      setRequestError("");
      const next = await getGitHubCopilotAuthStatus(controller.signal);
      if (isStale(seq)) return;
      applyStatus(next);
    } catch (error) {
      if (isStale(seq) || controller.signal.aborted) return;
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      if (pollAbortRef.current === controller) {
        pollAbortRef.current = null;
      }
      if (!isStale(seq)) {
        setLoading(false);
      }
    }
  }, [applyStatus, beginMutation, isStale]);

  useEffect(() => {
    mountedRef.current = true;
    void refresh();
    return () => {
      mountedRef.current = false;
      requestSeqRef.current += 1;
      pollAbortRef.current?.abort();
      pollAbortRef.current = null;
    };
  }, [refresh]);

  // Serial polling: never schedule the next GET until the previous one settles.
  useEffect(() => {
    if (!status || !shouldPollGitHubCopilotAuth(status)) return;
    let active = true;
    let timerId: number | null = null;

    const tick = async () => {
      const seq = requestSeqRef.current;
      const controller = new AbortController();
      pollAbortRef.current?.abort();
      pollAbortRef.current = controller;
      try {
        const next = await getGitHubCopilotAuthStatus(controller.signal);
        if (!active || isStale(seq)) return;
        setRequestError("");
        applyStatus(next);
        if (shouldPollGitHubCopilotAuth(next)) {
          timerId = window.setTimeout(() => void tick(), POLL_INTERVAL_MS);
        }
      } catch (error) {
        if (!active || isStale(seq) || controller.signal.aborted) return;
        setRequestError(error instanceof Error ? error.message : String(error));
        timerId = window.setTimeout(() => void tick(), POLL_INTERVAL_MS);
      } finally {
        if (pollAbortRef.current === controller) {
          pollAbortRef.current = null;
        }
      }
    };

    timerId = window.setTimeout(() => void tick(), POLL_INTERVAL_MS);
    return () => {
      active = false;
      if (timerId !== null) window.clearTimeout(timerId);
      pollAbortRef.current?.abort();
      pollAbortRef.current = null;
    };
  }, [applyStatus, isStale, pollNonce, status]);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const startLogin = async () => {
    const seq = beginMutation();
    setWorking(true);
    setRequestError("");
    setCopied(false);
    try {
      const next = await startGitHubCopilotLogin();
      if (isStale(seq)) return;
      applyStatus(next);
    } catch (error) {
      if (isStale(seq)) return;
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      if (!isStale(seq)) setWorking(false);
    }
  };

  const cancelLogin = async () => {
    const seq = beginMutation();
    setWorking(true);
    setRequestError("");
    try {
      const next = await cancelGitHubCopilotLogin();
      if (isStale(seq)) return;
      applyStatus(next);
    } catch (error) {
      if (isStale(seq)) return;
      setRequestError(error instanceof Error ? error.message : String(error));
      // Restart polling if the cancel request failed while authorization is still active.
      setPollNonce((n) => n + 1);
    } finally {
      if (!isStale(seq)) setWorking(false);
    }
  };

  const logout = async () => {
    const seq = beginMutation();
    setWorking(true);
    setRequestError("");
    try {
      const next = await logoutGitHubCopilot();
      if (isStale(seq)) return;
      applyStatus(next);
    } catch (error) {
      if (isStale(seq)) return;
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      if (!isStale(seq)) setWorking(false);
    }
  };

  const copyCode = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const errorKey =
    status?.error_code === "expired"
      ? "githubCopilot.auth.expired"
      : status?.error_code === "access_denied"
        ? "githubCopilot.auth.accessDenied"
        : status?.error_code === "network_error"
          ? "githubCopilot.auth.networkError"
          : status?.error_code === "credentials_invalid"
            ? "githubCopilot.auth.credentialsInvalid"
            : "githubCopilot.auth.failed";

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--muted)]/20 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[13px] font-medium text-[var(--foreground)]">
            {t("githubCopilot.auth.title")}
          </p>
          <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
            {t("githubCopilot.auth.description")}
          </p>
        </div>
        <Tooltip label={t("githubCopilot.auth.checkAgain")} side="top">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading || working}
            className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
            aria-label={t("githubCopilot.auth.checkAgain")}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </Tooltip>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {loading ? (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("githubCopilot.auth.checking")}
          </span>
        ) : status?.connection === "connected" ? (
          <>
            <span className="inline-flex items-center gap-1.5 text-[12px] text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-3.5 w-3.5" />
              {status.account_id
                ? t("githubCopilot.auth.loggedInAs", {
                    user: status.account_id,
                  })
                : t("githubCopilot.auth.loggedIn")}
            </span>
            <button
              type="button"
              onClick={() => void logout()}
              disabled={working}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[12px] hover:bg-[var(--muted)] disabled:opacity-50"
            >
              {working ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <LogOut className="h-3.5 w-3.5" />
              )}
              {t("githubCopilot.auth.logout")}
            </button>
          </>
        ) : status && shouldPollGitHubCopilotAuth(status) ? (
          <div className="w-full space-y-2.5">
            {status.user_code && (
              <div className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2">
                <span className="text-[11px] text-[var(--muted-foreground)]">
                  {t("githubCopilot.auth.codeLabel")}
                </span>
                <code className="font-mono text-[14px] font-semibold tracking-widest text-[var(--foreground)] select-all">
                  {status.user_code}
                </code>
                <button
                  type="button"
                  onClick={() => void copyCode(status.user_code!)}
                  className="ml-auto inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2 py-1 text-[11px] hover:bg-[var(--muted)]"
                >
                  {copied ? (
                    <Check className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />
                  ) : (
                    <Copy className="h-3 w-3" />
                  )}
                  {copied
                    ? t("githubCopilot.auth.copied")
                    : t("githubCopilot.auth.copyCode")}
                </button>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              {status.verification_uri && (
                <a
                  href={status.verification_uri}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-md bg-[var(--foreground)] px-3 py-1.5 text-[12px] text-[var(--background)]"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  {t("githubCopilot.auth.openAuthorization")}
                </a>
              )}
              <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--muted-foreground)]">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {t("githubCopilot.auth.waiting")}
              </span>
              <button
                type="button"
                onClick={() => void cancelLogin()}
                disabled={working}
                className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-[12px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
              >
                <X className="h-3.5 w-3.5" />
                {t("githubCopilot.auth.cancel")}
              </button>
            </div>
          </div>
        ) : (
          <>
            <button
              type="button"
              onClick={() => void startLogin()}
              disabled={working}
              className="inline-flex items-center gap-1.5 rounded-md bg-[var(--foreground)] px-3 py-1.5 text-[12px] text-[var(--background)] disabled:opacity-50"
            >
              {working ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <LogIn className="h-3.5 w-3.5" />
              )}
              {t("githubCopilot.auth.signIn")}
            </button>
            {status?.connection === "error" &&
              status.error_code === "credentials_invalid" && (
                <button
                  type="button"
                  onClick={() => void logout()}
                  disabled={working}
                  className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[12px] hover:bg-[var(--muted)] disabled:opacity-50"
                >
                  <LogOut className="h-3.5 w-3.5" />
                  {t("githubCopilot.auth.logout")}
                </button>
              )}
          </>
        )}
      </div>

      {(requestError || status?.connection === "error") && (
        <p className="mt-2 text-[11px] text-red-500">
          {requestError || t(errorKey)}
        </p>
      )}
    </div>
  );
}
