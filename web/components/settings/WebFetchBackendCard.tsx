"use client";

// Web fetch backend select — the Settings UI face of the persisted
// `web_fetch.backend` system setting (#2448). Reads `GET /api/settings/web-fetch`
// (choices come from the backend's FETCH_PROVIDERS table, never duplicated
// here) and saves through the global Apply bar like every other settings
// extension.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  SettingRow,
  SettingSection,
  selectClass,
  selectOptionClass,
} from "./shared";
import {
  type WebFetchSettingsPayload,
  webFetchBackendOptions,
  webFetchBackendValue,
} from "./web-fetch-backend";
import { useSettings } from "@/features/settings/store/SettingsStore";
import { apiFetch, apiUrl } from "@/lib/api";
import { EXTENSION_ENDPOINTS } from "@/lib/settings-extensions";

export function WebFetchBackendCard() {
  const { t } = useTranslation();
  const { catalogEditable, registerExtension, pendingExtensionPayload, draftRevision } =
    useSettings();
  const [payload, setPayload] = useState<WebFetchSettingsPayload | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (catalogEditable !== true) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await apiFetch(apiUrl(EXTENSION_ENDPOINTS["web-fetch"]));
        const data = (await response.json().catch(() => ({}))) as
          | WebFetchSettingsPayload
          | { detail?: string };
        if (!response.ok) {
          throw new Error(
            "detail" in data && data.detail
              ? String(data.detail)
              : t("Failed to load web fetch settings."),
          );
        }
        if (cancelled) return;
        const next = data as WebFetchSettingsPayload;
        setPayload(next);
        const pending = pendingExtensionPayload("web-fetch") as
          | { backend?: string }
          | undefined;
        setDraft(pending?.backend ?? next.settings.backend);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [catalogEditable, draftRevision, pendingExtensionPayload, t]);

  const options = useMemo(
    () => webFetchBackendOptions(payload?.choices, draft ?? payload?.settings.backend),
    [draft, payload],
  );
  const selected = webFetchBackendValue(draft, options);
  const dirty = Boolean(
    payload && draft !== null && payload.settings.backend !== selected,
  );

  // Flush through the global Apply (top toolbar) instead of a local button.
  // Refs keep the registered ``save`` closure reading the latest draft.
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const save = useCallback(async () => {
    const current = draftRef.current;
    if (current === null) return;
    setError(null);
    try {
      const response = await apiFetch(apiUrl(EXTENSION_ENDPOINTS["web-fetch"]), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backend: current }),
      });
      const data = (await response.json().catch(() => ({}))) as
        | WebFetchSettingsPayload
        | { detail?: string };
      if (!response.ok) {
        throw new Error(
          "detail" in data && data.detail
            ? String(data.detail)
            : t("Failed to save web fetch settings."),
        );
      }
      const next = data as WebFetchSettingsPayload;
      setPayload(next);
      setDraft(next.settings.backend);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    }
  }, [t]);

  useEffect(() => {
    if (catalogEditable !== true) return;
    registerExtension("web-fetch", {
      dirty,
      save,
      payload: draft === null ? null : { backend: draft },
    });
    return () => registerExtension("web-fetch", null);
  }, [catalogEditable, dirty, draft, save, registerExtension]);

  if (catalogEditable !== true) return null;

  return (
    <SettingSection
      title={t("Web fetch backend")}
      description={t(
        "Which service fetches and extracts pages for web_fetch calls.",
      )}
    >
      {loading && (
        <div className="flex items-center gap-2 py-5 text-[13px] text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("Loading web fetch settings...")}
        </div>
      )}
      {!loading && error && (
        <div className="my-4 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-600 dark:text-red-300">
          {error}
        </div>
      )}
      {!loading && payload && (
        <SettingRow
          title={t("Backend")}
          description={t("Applies from the next web_fetch onwards.")}
          control={
            <div className="relative">
              <select
                className={`${selectClass} w-56`}
                aria-label={t("Web fetch backend")}
                value={selected}
                onChange={(event) => setDraft(event.target.value)}
              >
                {options.map((option) => (
                  <option className={selectOptionClass} key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted-foreground)]" />
            </div>
          }
        />
      )}
      {!loading && payload && payload.effective.backend !== payload.settings.backend && (
        <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
          {t("DEEPTUTOR_FETCH_BACKEND is overriding the saved choice for this deployment.")}
        </p>
      )}
    </SettingSection>
  );
}
