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
import { Toggle } from "@/components/settings/Toggle";
import { useSettings } from "@/features/settings/store/SettingsStore";
import {
  allowPrivateTargets,
  isNetworkDraftDirty,
  networkDraftPayload,
  normalizeNetworkDraft,
  splitNetworkList,
  ssrfProtectionFromToggle,
  type NetworkSettings,
  type NetworkSettingsPayload,
} from "@/features/settings/sections/network-draft";
import { apiFetch, apiUrl } from "@/lib/api";
import {
  RuntimeHealthCard,
  TurnCoordinationSettings,
  useRuntimeStatus,
} from "@/features/runtime-status";

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

export default function NetworkSettingsPage() {
  const { t } = useTranslation();
  const runtime = useRuntimeStatus();
  const { registerExtension, pendingExtensionPayload, draftRevision } =
    useSettings();
  const apiBasePlaceholder = "https://api.example.com";
  const corsPlaceholder = "https://learn.example.com\nhttp://10.0.0.5:3782";
  const rangesPlaceholder = "198.18.0.0/15\nfd27:712::/32";
  const [payload, setPayload] = useState<NetworkSettingsPayload | null>(null);
  const [draft, setDraft] = useState<NetworkSettings | null>(null);
  const [corsText, setCorsText] = useState("");
  const [rangesText, setRangesText] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await apiFetch(apiUrl("/api/settings/network"));
        const data = (await response.json().catch(() => ({}))) as
          NetworkSettingsPayload | { detail?: string };
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
        const pending = pendingExtensionPayload("network") as
          NetworkSettings | undefined;
        const resolved = pending ?? normalizeNetworkDraft(next);
        setDraft(resolved);
        setCorsText((resolved.cors_origins || []).join("\n"));
        setRangesText((resolved.network_synthetic_ranges || []).join("\n"));
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
  }, [draftRevision, pendingExtensionPayload, t]);

  const dirty = useMemo(() => {
    if (!payload || !draft) return false;
    return isNetworkDraftDirty(payload, draft, corsText, rangesText);
  }, [corsText, draft, payload, rangesText]);

  // Flush through the global Apply (top toolbar) instead of a local button.
  // Refs keep the registered ``save`` closure reading the latest draft.
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const corsRef = useRef(corsText);
  corsRef.current = corsText;
  const rangesRef = useRef(rangesText);
  rangesRef.current = rangesText;
  const save = useCallback(async () => {
    const current = draftRef.current;
    if (!current) return;
    setError(null);
    try {
      const response = await apiFetch(apiUrl("/api/settings/network"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          networkDraftPayload(current, corsRef.current, rangesRef.current),
        ),
      });
      const data = (await response.json().catch(() => ({}))) as
        NetworkSettingsPayload | { detail?: string };
      if (!response.ok) {
        throw new Error(
          "detail" in data && data.detail
            ? data.detail
            : t("Failed to save network settings."),
        );
      }
      const next = data as NetworkSettingsPayload;
      setPayload(next);
      setDraft(normalizeNetworkDraft(next));
      setCorsText((next.settings.cors_origins || []).join("\n"));
      setRangesText((next.settings.network_synthetic_ranges || []).join("\n"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    }
  }, [t]);

  useEffect(() => {
    registerExtension("network", {
      dirty,
      save,
      payload: draft
        ? networkDraftPayload(draft, corsText, rangesText)
        : null,
    });
    return () => registerExtension("network", null);
  }, [dirty, draft, corsText, rangesText, save, registerExtension]);

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

      <div className="mb-7">
        <RuntimeHealthCard
          snapshot={runtime}
          onRefresh={runtime.refresh}
          showDetails
        />
        {runtime.data ? (
          <TurnCoordinationSettings
            value={{
              backendWorkers: runtime.data.workerCount,
              coordinationMode: runtime.data.coordinationMode,
              developmentReload: false,
              leaseTtlSeconds: runtime.data.leaseTtlSeconds,
              recoveryIntervalSeconds: runtime.data.recoveryIntervalSeconds,
            }}
            redisConfigured={runtime.data.redisConfigured}
          />
        ) : null}
      </div>

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

          <SettingSection
            title={t("Outbound requests")}
            description={t(
              "How the server reaches MCP servers, web pages and channel media. These guards apply immediately, without a restart.",
            )}
          >
            <SettingRow
              title={t("Allow private network targets")}
              description={t(
                "Self-hosted LAN only: reach MCP servers, intranet pages and channel media on RFC1918, CGNAT or ULA addresses. Loopback, link-local and cloud-metadata addresses stay blocked.",
              )}
              control={
                <Toggle
                  checked={allowPrivateTargets(draft)}
                  onChange={(allowPrivate) =>
                    setDraft((current) =>
                      current
                        ? {
                            ...current,
                            ssrf_protection_enabled:
                              ssrfProtectionFromToggle(allowPrivate),
                          }
                        : current,
                    )
                  }
                />
              }
            />
            <div className="py-4">
              <label
                className="mb-1.5 block text-[13px] font-medium"
                htmlFor="network-synthetic-ranges"
              >
                {t("Fake-IP proxy ranges")}
              </label>
              <textarea
                id="network-synthetic-ranges"
                className={`${inputClass} min-h-24 resize-y font-mono text-[12.5px] leading-relaxed disabled:opacity-50`}
                placeholder={rangesPlaceholder}
                value={rangesText}
                disabled={allowPrivateTargets(draft)}
                onChange={(event) => setRangesText(event.target.value)}
              />
              <p className="mt-2 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
                {t(
                  "Only needed behind a local Clash, Mihomo, Loon or sing-box proxy in Fake-IP mode: one CIDR per line, for example 198.18.0.0/15 or fd27:712::/32. A hostname resolving into one of these ranges is treated as public; IP literal URLs, loopback and metadata answers stay blocked.",
                )}
              </p>
              {allowPrivateTargets(draft) && (
                <p className="mt-1 text-[11.5px] leading-relaxed text-amber-700 dark:text-amber-300">
                  {t(
                    "Ignored while private network targets are allowed above.",
                  )}
                </p>
              )}
              {payload.effective.ssrf_policy_env_override && (
                <p className="mt-1 text-[11.5px] leading-relaxed text-amber-700 dark:text-amber-300">
                  {t(
                    "A deployment environment variable overrides these values; editing here does not change the running server.",
                  )}
                </p>
              )}
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
