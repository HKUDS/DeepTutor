"use client";

import {
  CheckCircle2,
  ExternalLink,
  Loader2,
  LogIn,
  LogOut,
  RefreshCw,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  cancelCodeBuddyLogin,
  getCodeBuddyAuthStatus,
  logoutCodeBuddy,
  shouldPollCodeBuddyAuth,
  startCodeBuddyLogin,
  type CodeBuddyAuthStatus,
} from "@/lib/codebuddy-auth";

export function CodeBuddyAuthCard() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<CodeBuddyAuthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [requestError, setRequestError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setRequestError("");
      setStatus(await getCodeBuddyAuthStatus());
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!status || !shouldPollCodeBuddyAuth(status)) return;
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => window.clearInterval(timer);
  }, [refresh, status]);

  const startLogin = async () => {
    setWorking(true);
    setRequestError("");
    const popup = window.open("about:blank", "_blank");
    try {
      const next = await startCodeBuddyLogin();
      setStatus(next);
      if (next.authorize_url) {
        if (popup) popup.location.href = next.authorize_url;
      } else {
        popup?.close();
      }
    } catch (error) {
      popup?.close();
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
    }
  };

  const cancelLogin = async () => {
    setWorking(true);
    try {
      setStatus(await cancelCodeBuddyLogin());
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
    }
  };

  const logout = async () => {
    setWorking(true);
    setRequestError("");
    try {
      setStatus(await logoutCodeBuddy());
    } catch (error) {
      setRequestError(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
    }
  };

  const errorKey =
    status?.error_code === "sdk_missing"
      ? "codebuddy.auth.sdkMissing"
      : status?.error_code === "cli_missing"
        ? "codebuddy.auth.cliMissing"
        : status?.error_code === "login_timeout"
          ? "codebuddy.auth.timeout"
          : status?.error_code === "logout_external"
            ? "codebuddy.auth.logoutExternal"
            : "codebuddy.auth.failed";

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--muted)]/20 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[13px] font-medium text-[var(--foreground)]">
            {t("codebuddy.auth.title")}
          </p>
          <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
            {t("codebuddy.auth.description")}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading || working}
          className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
          title={t("codebuddy.auth.checkAgain")}
          aria-label={t("codebuddy.auth.checkAgain")}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {loading ? (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            {t("codebuddy.auth.checking")}
          </span>
        ) : status?.connection === "connected" ? (
          <>
            <span className="inline-flex items-center gap-1.5 text-[12px] text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-3.5 w-3.5" />
              {status.user_label
                ? t("codebuddy.auth.loggedInAs", { user: status.user_label })
                : t("codebuddy.auth.loggedIn")}
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
              {t("codebuddy.auth.logout")}
            </button>
          </>
        ) : status && shouldPollCodeBuddyAuth(status) ? (
          <>
            <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--muted-foreground)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t("codebuddy.auth.waiting")}
            </span>
            {status.authorize_url && (
              <a
                href={status.authorize_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[12px] hover:bg-[var(--muted)]"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                {t("codebuddy.auth.openAuthorization")}
              </a>
            )}
            <button
              type="button"
              onClick={() => void cancelLogin()}
              disabled={working}
              className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-[12px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            >
              <X className="h-3.5 w-3.5" />
              {t("codebuddy.auth.cancel")}
            </button>
          </>
        ) : (
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
            {t("codebuddy.auth.signIn")}
          </button>
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
