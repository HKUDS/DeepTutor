"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useSettings } from "@/features/settings/store/SettingsStore";
import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateLLMOptionsCache } from "@/lib/llm-options";
import { registryButton, registryDanger, registryPrimary } from "./RegistryControls";
import { subPanelClass } from "./shared";

type AccountStatus = {
  state: "idle" | "pending" | "connected" | "error";
  user_code?: string;
  verification_uri?: string;
  verification_uri_complete?: string;
  expires_at?: string;
  user?: { email: string };
  account?: { name: string };
  public_url?: string;
  paid_balance?: number | null;
  models?: { id: string; label: string; available: boolean }[];
  message?: string;
};

const AUTH_PATH = "/api/settings/providers/deeptutor/auth";

async function request(
  action: "status" | "start" | "cancel" | "logout" | "models",
  deviceLabel?: string,
): Promise<AccountStatus> {
  const response = await apiFetch(apiUrl(`${AUTH_PATH}/${action}`), {
    method: action === "status" ? "GET" : "POST",
    ...(deviceLabel ? {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_label: deviceLabel }),
    } : {}),
    skipAuthRedirect: true,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data?.detail?.message || "");
  return data;
}

export function DeepTutorAccountCard() {
  const { t, i18n } = useTranslation();
  const { hasUnsavedChanges, reloadSettings, setToast } = useSettings();
  const [status, setStatus] = useState<AccountStatus>();
  const [deviceLabel, setDeviceLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const pending = status?.state === "pending";
  const connected = status?.state === "connected";
  const loadError = t("Could not update the DeepTutor Studio connection.");

  const syncCatalog = useCallback(async () => {
    invalidateLLMOptionsCache();
    if (hasUnsavedChanges) {
      setToast(t("Save or discard your settings edits to reload the model list."));
      return;
    }
    await reloadSettings();
  }, [hasUnsavedChanges, reloadSettings, setToast, t]);

  useEffect(() => {
    let active = true;
    void request("status").then((current) => {
      if (active) setStatus(current);
    }).catch(() => {
      if (active) setError(loadError);
    });
    return () => { active = false; };
  }, [loadError]);

  useEffect(() => {
    if (!pending || busy) return;
    let active = true;
    let timeout: number;
    const poll = async () => {
      try {
        const current = await request("status");
        if (!active) return;
        setError("");
        setStatus(current);
        if (current.state === "connected") await syncCatalog();
        if (current.state !== "pending") return;
      } catch {
        if (active) setError(loadError);
      }
      if (active) timeout = window.setTimeout(poll, 1500);
    };
    timeout = window.setTimeout(poll, 1500);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [pending, busy, loadError, syncCatalog]);

  const run = async (action: "start" | "cancel" | "logout" | "models") => {
    setBusy(true);
    setError("");
    setCopied(false);
    try {
      const current = await request(action, action === "start" ? deviceLabel.trim() : undefined);
      setStatus(current);
      if (action === "logout" || action === "models") await syncCatalog();
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : loadError);
      if (action === "models") {
        const current = await request("status").catch(() => undefined);
        if (current) {
          setStatus(current);
          if (current.state === "idle") await syncCatalog();
        }
      }
    } finally {
      setBusy(false);
    }
  };

  const copyCode = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
    } catch {
      setError(t("Could not copy the code. Select it to copy it manually."));
    }
  };
  const creditsUrl = status?.public_url ? `${status.public_url}/account/credits` : undefined;
  const deviceUrl = status?.public_url ? `${status.public_url}/account/device` : undefined;
  const models = status?.models ?? [];

  return (
    <section className={`space-y-3 p-4 sm:p-5 ${subPanelClass}`} aria-label={t("DeepTutor Studio account")}>
      <h2 className="text-sm font-semibold">{t("DeepTutor Studio account")}</h2>
      <p className="text-sm text-[var(--muted-foreground)]">
        {t("Sign in to use official models with your paid credits. You can disconnect this device from your Studio account.")}
      </p>
      {pending ? (
        <div className="flex flex-wrap items-center gap-2" role="status">
          {status?.user_code && (
            <>
              <code className="select-all rounded-md bg-[var(--muted)] px-2 py-1 font-mono text-sm">
                {status.user_code}
              </code>
              <button type="button" className={registryButton} onClick={() => void copyCode(status.user_code!)}>
                {copied ? t("Copied") : t("Copy code")}
              </button>
            </>
          )}
          {status?.verification_uri && (
            <a className={registryPrimary} href={status.verification_uri_complete || status.verification_uri} target="_blank" rel="noreferrer">
              {t("Open in browser")}
            </a>
          )}
          <button type="button" className={registryButton} disabled={busy} onClick={() => void run("cancel")}>
            {t("Cancel")}
          </button>
        </div>
      ) : connected ? (
        <>
          <p className="break-words text-sm">{status.user?.email} · {status.account?.name}</p>
          {typeof status.paid_balance === "number" && (
            <p className="text-sm">{t("Paid credits remaining {{balance}}", {
              balance: new Intl.NumberFormat(i18n.resolvedLanguage).format(status.paid_balance),
            })}</p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={registryButton} disabled={busy} onClick={() => void run("models")}>
              {t("Refresh models")}
            </button>
            {creditsUrl && (
              <a className={registryButton} href={creditsUrl} target="_blank" rel="noreferrer">{t("Buy credits")}</a>
            )}
            {deviceUrl && (
              <a className={registryButton} href={deviceUrl} target="_blank" rel="noreferrer">{t("Device authorizations")}</a>
            )}
            <button type="button" className={registryDanger} disabled={busy} onClick={() => void run("logout")}>
              {t("Sign out")}
            </button>
          </div>
          {models.length > 0 && (
            <ul className="flex flex-wrap gap-2" aria-label={t("Language models")}>
              {models.map((model) => (
                <li key={model.id} className={`rounded-md border px-2 py-1 text-xs ${model.available ? "" : "text-[var(--muted-foreground)]"}`}>
                  {model.label}
                  {!model.available && ` · ${t("Requires paid credits")}`}
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <input
            aria-label={t("Device name")}
            className="min-w-0 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-sm"
            maxLength={64}
            placeholder={t("Device name (optional)")}
            value={deviceLabel}
            onChange={(event) => setDeviceLabel(event.target.value)}
          />
          <button type="button" className={registryPrimary} disabled={busy} onClick={() => void run("start")}>
            {t("Sign in to DeepTutor Studio")}
          </button>
        </div>
      )}
      {(error || status?.message) && <p role="alert" className="text-sm text-[var(--destructive)]">{error || status?.message}</p>}
    </section>
  );
}
