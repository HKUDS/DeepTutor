"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, RefreshCw, ShieldCheck, Unplug } from "lucide-react";
import { useTranslation } from "react-i18next";

import Button from "@/components/ui/Button";
import {
  cancelCodexLogin,
  CodexOAuthApiError,
  codexErrorMessageKey,
  codexStatusMessageKey,
  getCodexStatus,
  logoutCodex,
  refreshCodexModels,
  shouldPollCodexStatus,
  startCodexLogin,
  type CodexOAuthStatus,
} from "@/lib/codex-oauth";

import { useSettings } from "./SettingsContext";

export function CodexOAuthCard() {
  const { t } = useTranslation();
  const { reloadSettings } = useSettings();
  const [status, setStatus] = useState<CodexOAuthStatus | null>(null);
  const [pending, setPending] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const reloadedOperation = useRef<string | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const next = await getCodexStatus();
      setStatus(next);
      setErrorKey(null);
      return next;
    } catch (error) {
      setErrorKey(
        codexErrorMessageKey(
          error instanceof CodexOAuthApiError ? error.code : null,
        ),
      );
      return null;
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    if (!status || !shouldPollCodexStatus(status)) return;
    const timer = window.setTimeout(() => void loadStatus(), 1_000);
    return () => window.clearTimeout(timer);
  }, [loadStatus, status]);

  useEffect(() => {
    if (
      status?.operation_state !== "completed" ||
      !status.operation_id ||
      reloadedOperation.current === status.operation_id
    ) {
      return;
    }
    reloadedOperation.current = status.operation_id;
    void reloadSettings();
  }, [reloadSettings, status]);

  const signIn = async () => {
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
      setStatus(await getCodexStatus());
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

  const cancel = async () => {
    setPending(true);
    try {
      setStatus(await cancelCodexLogin());
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

  const refresh = async () => {
    setPending(true);
    try {
      setStatus(await refreshCodexModels());
      await reloadSettings();
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
    setPending(true);
    try {
      setStatus(await logoutCodex());
      await reloadSettings();
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
  const messageKey = errorKey || (status ? codexStatusMessageKey(status) : null);

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--muted)]/30 p-4">
      <div className="flex items-start gap-3">
        <ShieldCheck className="mt-0.5 h-5 w-5 text-[var(--primary)]" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{t("codex.oauth.title")}</p>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            {t("codex.oauth.isolated")}
          </p>
          <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
            {t("codex.oauth.experimental")}
          </p>
          {messageKey && (
            <p className="mt-3 text-sm text-[var(--foreground)]">
              {t(messageKey)}
            </p>
          )}
          {connected && status?.model_count !== undefined && (
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              {t("codex.oauth.modelCount", { count: status.model_count })}
            </p>
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
            {polling && (
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
