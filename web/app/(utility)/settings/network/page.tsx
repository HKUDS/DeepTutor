"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
  inputClass,
} from "@/components/settings/shared";
import { useSettings } from "@/components/settings/SettingsContext";
import {
  DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS,
  MAX_CHAT_RESPONSE_TIMEOUT_SECONDS,
  MIN_CHAT_RESPONSE_TIMEOUT_SECONDS,
  clampChatResponseTimeout,
  writeStoredChatResponseTimeout,
} from "@/context/app-shell-storage";
import { apiFetch, apiUrl } from "@/lib/api";

type NetworkSettings = {
  backend_port: number;
  frontend_port: number;
  public_api_base: string;
  cors_origins: string[];
};

type NetworkSettingsPayload = {
  settings: NetworkSettings;
  effective: {
    backend_url: string;
    frontend_url: string;
    browser_api_base: string;
    api_base_source: string;
    cors_mode: "explicit" | "permissive";
    cors_origins: string[];
    allow_remote_http_origins: boolean;
  };
  auth: {
    enabled: boolean;
    cookie_secure: boolean;
    cookie_samesite: string;
    cross_site_cookie_ready: boolean;
  };
  restart_required: boolean;
};

function splitOrigins(value: string): string[] {
  return value
    .split(/[,;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeDraft(payload: NetworkSettingsPayload): NetworkSettings {
  return {
    backend_port: payload.settings.backend_port,
    frontend_port: payload.settings.frontend_port,
    public_api_base: payload.settings.public_api_base || "",
    cors_origins: payload.settings.cors_origins || [],
  };
}

function DetailTile({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "ok" | "warn";
}) {
  const dot =
    tone === "ok"
      ? "bg-emerald-500"
      : tone === "warn"
        ? "bg-amber-500"
        : "bg-[var(--border)]";
  return (
    <div className="rounded-xl border border-[var(--border)]/60 bg-[var(--card)] px-4 py-3">
      <div className="flex items-center gap-2 text-[11px] font-medium text-[var(--muted-foreground)]">
        <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
        {label}
      </div>
      <div
        className="mt-2 truncate text-[13px] font-medium text-[var(--foreground)]"
        title={value}
      >
        {value || "-"}
      </div>
    </div>
  );
}

/**
 * Per-user chat idle-timeout control. Self-contained (its own fetch + save via
 * the dedicated ``/settings/chat-response-timeout`` endpoint) and renders
 * independently of the admin network settings below, so any user can adjust it.
 * Mirrors the value to localStorage so the chat watchdog picks it up at once.
 */
function ChatResponseTimeoutSection() {
  const { t } = useTranslation();
  const { registerExtension } = useSettings();
  const [seconds, setSeconds] = useState<number>(
    DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS,
  );
  const [initial, setInitial] = useState<number>(
    DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS,
  );
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await apiFetch(apiUrl("/api/v1/settings"));
        const data = (await response.json().catch(() => ({}))) as {
          ui?: { chat_response_timeout?: number };
        };
        const value = clampChatResponseTimeout(
          Number(data?.ui?.chat_response_timeout) ||
            DEFAULT_CHAT_RESPONSE_TIMEOUT_SECONDS,
        );
        if (cancelled) return;
        setSeconds(value);
        setInitial(value);
        writeStoredChatResponseTimeout(value);
      } catch {
        // keep the default
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const dirty = seconds !== initial;

  // Flush through the global Apply (top toolbar) instead of a local button.
  const secondsRef = useRef(seconds);
  secondsRef.current = seconds;
  const save = useCallback(async () => {
    setMessage("");
    try {
      const value = clampChatResponseTimeout(secondsRef.current);
      const response = await apiFetch(
        apiUrl("/api/v1/settings/chat-response-timeout"),
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_response_timeout: value }),
        },
      );
      if (!response.ok) throw new Error(t("Failed to save."));
      setSeconds(value);
      setInitial(value);
      writeStoredChatResponseTimeout(value);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }, [t]);

  useEffect(() => {
    registerExtension("chat-timeout", { dirty, save });
    return () => registerExtension("chat-timeout", null);
  }, [dirty, save, registerExtension]);

  return (
    <SettingSection
      title={t("Chat response timeout")}
      description={t(
        "How long chat waits for a reply before showing a timeout error. Increase it for slow tools like image or video generation.",
      )}
    >
      <SettingRow
        title={t("Timeout (seconds)")}
        description={t(
          "Between {{min}} and {{max}} seconds. Takes effect immediately — no restart.",
          {
            min: MIN_CHAT_RESPONSE_TIMEOUT_SECONDS,
            max: MAX_CHAT_RESPONSE_TIMEOUT_SECONDS,
          },
        )}
        control={
          <input
            className={`${inputClass} w-28`}
            type="number"
            min={MIN_CHAT_RESPONSE_TIMEOUT_SECONDS}
            max={MAX_CHAT_RESPONSE_TIMEOUT_SECONDS}
            value={seconds}
            onChange={(event) => setSeconds(Number(event.target.value))}
          />
        }
      />
      {message && (
        <p className="px-1 pb-3 text-[11.5px] text-[var(--muted-foreground)]">
          {message}
        </p>
      )}
    </SettingSection>
  );
}

export default function NetworkSettingsPage() {
  const { t } = useTranslation();
  const { registerExtension } = useSettings();
  const apiBasePlaceholder = "https://api.example.com";
  const corsPlaceholder = "https://learn.example.com\nhttp://10.0.0.5:3782";
  const [payload, setPayload] = useState<NetworkSettingsPayload | null>(null);
  const [draft, setDraft] = useState<NetworkSettings | null>(null);
  const [corsText, setCorsText] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await apiFetch(apiUrl("/api/v1/settings/network"));
        const data = (await response.json().catch(() => ({}))) as
          | NetworkSettingsPayload
          | { detail?: string };
        if (!response.ok) {
          throw new Error(
            "detail" in data && data.detail
              ? data.detail
              : t("Failed to load network settings."),
          );
        }
        if (cancelled) return;
        const next = data as NetworkSettingsPayload;
        setPayload(next);
        setDraft(normalizeDraft(next));
        setCorsText((next.settings.cors_origins || []).join("\n"));
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const dirty = useMemo(() => {
    if (!payload || !draft) return false;
    const current = normalizeDraft(payload);
    return (
      current.backend_port !== draft.backend_port ||
      current.frontend_port !== draft.frontend_port ||
      current.public_api_base !== draft.public_api_base ||
      JSON.stringify(current.cors_origins) !==
        JSON.stringify(splitOrigins(corsText))
    );
  }, [corsText, draft, payload]);

  // Flush through the global Apply (top toolbar) instead of a local button.
  // Refs keep the registered ``save`` closure reading the latest draft.
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const corsRef = useRef(corsText);
  corsRef.current = corsText;
  const save = useCallback(async () => {
    const current = draftRef.current;
    if (!current) return;
    setError(null);
    try {
      const response = await apiFetch(apiUrl("/api/v1/settings/network"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...current,
          cors_origins: splitOrigins(corsRef.current),
        }),
      });
      const data = (await response.json().catch(() => ({}))) as
        | NetworkSettingsPayload
        | { detail?: string };
      if (!response.ok) {
        throw new Error(
          "detail" in data && data.detail
            ? data.detail
            : t("Failed to save network settings."),
        );
      }
      const next = data as NetworkSettingsPayload;
      setPayload(next);
      setDraft(normalizeDraft(next));
      setCorsText((next.settings.cors_origins || []).join("\n"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [t]);

  useEffect(() => {
    registerExtension("network", { dirty, save });
    return () => registerExtension("network", null);
  }, [dirty, save, registerExtension]);

  return (
    <div data-tour="tour-network">
      <SettingsPageHeader
        title={t("Network")}
        description={t(
          "Control the browser-facing API URL and CORS origins used by Docker, LAN, and reverse-proxy deployments.",
        )}
      />

      <p className="mb-7 text-[12px] text-[var(--muted-foreground)]">
        {t("Network changes take effect after restart.")}
      </p>

      <ChatResponseTimeoutSection />

      {loading && (
        <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("Loading network settings...")}
        </div>
      )}

      {!loading && error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-600 dark:text-red-300">
          {error}
        </div>
      )}

      {!loading && payload && draft && (
        <>
          <div className="mb-7 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            <DetailTile
              label={t("Browser API")}
              value={payload.effective.browser_api_base}
              tone="ok"
            />
            <DetailTile
              label={t("CORS mode")}
              value={
                payload.effective.cors_mode === "permissive"
                  ? t("Permissive until auth is enabled")
                  : t("Explicit origins required")
              }
              tone={
                payload.effective.cors_mode === "permissive" ? "ok" : "warn"
              }
            />
            <DetailTile
              label={t("Auth cookie")}
              value={`${payload.auth.cookie_samesite}${
                payload.auth.cookie_secure ? " + Secure" : ""
              }`}
              tone={
                !payload.auth.enabled || payload.auth.cross_site_cookie_ready
                  ? "ok"
                  : "warn"
              }
            />
            <DetailTile
              label={t("Restart")}
              value={t("Required after save")}
              tone="warn"
            />
          </div>

          <SettingSection
            title={t("Runtime ports")}
            description={t(
              "These ports are read during startup. Docker port mappings must match the container-side values.",
            )}
          >
            <SettingRow
              title={t("Backend port")}
              description={t("FastAPI listens on this port.")}
              control={
                <input
                  className={`${inputClass} w-28`}
                  type="number"
                  min={1}
                  max={65535}
                  value={draft.backend_port}
                  onChange={(event) =>
                    setDraft((current) =>
                      current
                        ? {
                            ...current,
                            backend_port: Number(event.target.value),
                          }
                        : current,
                    )
                  }
                />
              }
            />
            <SettingRow
              title={t("Frontend port")}
              description={t("Next.js serves the Web UI on this port.")}
              control={
                <input
                  className={`${inputClass} w-28`}
                  type="number"
                  min={1}
                  max={65535}
                  value={draft.frontend_port}
                  onChange={(event) =>
                    setDraft((current) =>
                      current
                        ? {
                            ...current,
                            frontend_port: Number(event.target.value),
                          }
                        : current,
                    )
                  }
                />
              }
            />
          </SettingSection>

          <SettingSection
            title={t("Browser API base")}
            description={t(
              "Set this when the browser cannot reach the backend through localhost, such as remote Docker or a reverse proxy.",
            )}
          >
            <SettingRow
              title={t("Public API base")}
              description={t(
                "Leave blank for local Docker. Use the externally reachable backend URL, including any proxy path.",
              )}
              control={
                <input
                  className={`${inputClass} w-[360px] max-w-[48vw]`}
                  placeholder={apiBasePlaceholder}
                  value={draft.public_api_base}
                  onChange={(event) =>
                    setDraft((current) =>
                      current
                        ? { ...current, public_api_base: event.target.value }
                        : current,
                    )
                  }
                />
              }
            />
          </SettingSection>

          <SettingSection
            title={t("CORS origins")}
            description={t(
              "Only required for authenticated cross-origin deployments. Use frontend origins, not API URLs.",
            )}
          >
            <div className="py-4">
              <textarea
                className={`${inputClass} min-h-28 resize-y font-mono text-[12.5px] leading-relaxed`}
                placeholder={corsPlaceholder}
                value={corsText}
                onChange={(event) => setCorsText(event.target.value)}
              />
              <p className="mt-2 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "Comma, semicolon, and newline separators are accepted. Bare host:port values are stored as http://host:port.",
                )}
              </p>
            </div>
          </SettingSection>

          {payload.auth.enabled && !payload.auth.cookie_secure && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-[12.5px] leading-relaxed text-amber-700 dark:text-amber-300">
              {t(
                "Auth is enabled but secure cookies are off. Cross-site HTTPS deployments should set auth.cookie_secure=true and restart so SameSite=None cookies work in modern browsers.",
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
