"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
  inputClass,
} from "@/components/settings/shared";
import { useSettings } from "@/features/settings/store/SettingsStore";
import { apiFetch, apiUrl } from "@/lib/api";
import { EXTENSION_ENDPOINTS } from "@/lib/settings-extensions";

type StarterSettings = { trace_count: number };

type StarterSettingsPayload = {
  settings: StarterSettings;
  bounds: { trace_count: [number, number] };
};

export default function StarterSettingsPage() {
  const { t } = useTranslation();
  const { registerExtension, pendingExtensionPayload, draftRevision } =
    useSettings();
  const [payload, setPayload] = useState<StarterSettingsPayload | null>(null);
  const [draft, setDraft] = useState<StarterSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await apiFetch(
          apiUrl(EXTENSION_ENDPOINTS["chat-starters"]),
        );
        const data = (await response.json().catch(() => ({}))) as
          | StarterSettingsPayload
          | { detail?: string };
        if (!response.ok) {
          throw new Error(
            "detail" in data && data.detail
              ? String(data.detail)
              : t("Failed to load starter settings."),
          );
        }
        if (cancelled) return;
        const next = data as StarterSettingsPayload;
        setPayload(next);
        // An edit left behind earlier in this session (or parked in a saved
        // draft) wins over the server value — leaving the page is not a way
        // to discard changes.
        const pending = pendingExtensionPayload("chat-starters") as
          | StarterSettings
          | undefined;
        setDraft(pending ? { ...pending } : { ...next.settings });
      } catch (err) {
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [draftRevision, pendingExtensionPayload, t]);

  const dirty = useMemo(
    () =>
      Boolean(
        payload && draft && payload.settings.trace_count !== draft.trace_count,
      ),
    [draft, payload],
  );

  // Flush through the global Apply (top toolbar) instead of a local button.
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const save = useCallback(async () => {
    const current = draftRef.current;
    if (!current) return;
    setError(null);
    try {
      const response = await apiFetch(
        apiUrl(EXTENSION_ENDPOINTS["chat-starters"]),
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(current),
        },
      );
      const data = (await response.json().catch(() => ({}))) as
        | StarterSettingsPayload
        | { detail?: string };
      if (!response.ok) {
        throw new Error(
          "detail" in data && data.detail
            ? String(data.detail)
            : t("Failed to save starter settings."),
        );
      }
      const next = data as StarterSettingsPayload;
      setPayload(next);
      setDraft({ ...next.settings });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [t]);

  useEffect(() => {
    registerExtension("chat-starters", { dirty, save, payload: draft });
    return () => registerExtension("chat-starters", null);
  }, [dirty, draft, save, registerExtension]);

  const bounds = payload?.bounds.trace_count;

  return (
    <div>
      <SettingsPageHeader
        title={t("Starting points")}
        description={t(
          "The three lines under the composer on an empty home screen, generated from your long-term memory and what you have been working on lately.",
        )}
      />

      {loading && (
        <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("Loading starter settings...")}
        </div>
      )}

      {!loading && error && (
        <div className="mb-5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-600 dark:text-red-300">
          {error}
        </div>
      )}

      {!loading && payload && draft && (
        <SettingSection
          title={t("Material")}
          description={t(
            "Your consolidated memory is always included. This controls how much raw recent activity goes with it — conversations, practice questions, searches, documents, in one list ordered by time.",
          )}
        >
          <SettingRow
            title={t("Recent activities")}
            description={t(
              "More gives the model a longer view of what you have touched; fewer keeps it focused on this week. Takes effect the next time the lines are regenerated.",
            )}
            control={
              <input
                className={`${inputClass} w-28`}
                type="number"
                min={bounds?.[0] ?? 3}
                max={bounds?.[1] ?? 100}
                value={draft.trace_count}
                onChange={(event) =>
                  setDraft((current) =>
                    current
                      ? { ...current, trace_count: Number(event.target.value) }
                      : current,
                  )
                }
              />
            }
          />
        </SettingSection>
      )}

      {!loading && payload && (
        <p className="mt-5 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
          {t("These lines are written by the active model unless you pin one.")}{" "}
          <Link
            href="/settings#task-models"
            className="inline-flex items-center gap-1 text-[var(--foreground)] underline-offset-2 hover:underline"
          >
            {t("Task models")}
            <ArrowUpRight className="h-3 w-3" />
          </Link>
        </p>
      )}
    </div>
  );
}
