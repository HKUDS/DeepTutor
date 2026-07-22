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
import { apiFetch, apiUrl } from "@/lib/api";

type AttachmentSettings = {
  max_file_mb: number;
  max_total_mb: number;
  max_chars_per_doc: number;
  max_chars_total: number;
};

type AttachmentSettingsPayload = {
  settings: AttachmentSettings;
  effective: {
    max_file_bytes: number;
    max_total_bytes: number;
    max_chars_per_doc: number;
    max_chars_total: number;
    ws_max_size: number;
  };
  bounds: {
    max_file_mb: [number, number];
    max_total_mb: [number, number];
    chars: [number, number];
  };
  restart_required_for_larger_uploads: boolean;
};

function normalizeDraft(
  payload: AttachmentSettingsPayload,
): AttachmentSettings {
  return { ...payload.settings };
}

export default function AttachmentSettingsPage() {
  const { t } = useTranslation();
  const { registerExtension } = useSettings();
  const [payload, setPayload] = useState<AttachmentSettingsPayload | null>(
    null,
  );
  const [draft, setDraft] = useState<AttachmentSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await apiFetch(
          apiUrl("/api/v1/settings/chat-attachments"),
        );
        const data = (await response.json().catch(() => ({}))) as
          | AttachmentSettingsPayload
          | { detail?: string };
        if (!response.ok) {
          throw new Error(
            "detail" in data && data.detail
              ? data.detail
              : t("Failed to load attachment settings."),
          );
        }
        if (cancelled) return;
        const next = data as AttachmentSettingsPayload;
        setPayload(next);
        setDraft(normalizeDraft(next));
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
      current.max_file_mb !== draft.max_file_mb ||
      current.max_total_mb !== draft.max_total_mb ||
      current.max_chars_per_doc !== draft.max_chars_per_doc ||
      current.max_chars_total !== draft.max_chars_total
    );
  }, [draft, payload]);

  // Flush through the global Apply (top toolbar) instead of a local button.
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const save = useCallback(async () => {
    const current = draftRef.current;
    if (!current) return;
    setError(null);
    try {
      const response = await apiFetch(
        apiUrl("/api/v1/settings/chat-attachments"),
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(current),
        },
      );
      const data = (await response.json().catch(() => ({}))) as
        | AttachmentSettingsPayload
        | { detail?: string };
      if (!response.ok) {
        throw new Error(
          "detail" in data && data.detail
            ? String(data.detail)
            : t("Failed to save attachment settings."),
        );
      }
      const next = data as AttachmentSettingsPayload;
      setPayload(next);
      setDraft(normalizeDraft(next));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [t]);

  useEffect(() => {
    registerExtension("chat-attachments", { dirty, save });
    return () => registerExtension("chat-attachments", null);
  }, [dirty, save, registerExtension]);

  const setField = (field: keyof AttachmentSettings) => (value: number) =>
    setDraft((current) => (current ? { ...current, [field]: value } : current));

  const bounds = payload?.bounds;

  return (
    <div>
      <SettingsPageHeader
        title={t("Attachments")}
        description={t(
          "Upload caps and extraction budgets for files attached in chat — shared by the main chat, books, quiz follow-ups, and partners.",
        )}
      />

      {loading && (
        <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("Loading attachment settings...")}
        </div>
      )}

      {!loading && error && (
        <div className="mb-5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-600 dark:text-red-300">
          {error}
        </div>
      )}

      {!loading && payload && draft && (
        <>
          <SettingSection
            title={t("Size limits")}
            description={t(
              "Caps are enforced when a file is picked and again server-side on every message. Lower limits apply immediately; raising them needs a backend restart so larger uploads fit through the WebSocket transport.",
            )}
          >
            <SettingRow
              title={t("Max file size (MB)")}
              description={t("Largest single file the composer accepts.")}
              control={
                <input
                  className={`${inputClass} w-28`}
                  type="number"
                  min={bounds?.max_file_mb[0] ?? 1}
                  max={bounds?.max_file_mb[1] ?? 1024}
                  value={draft.max_file_mb}
                  onChange={(event) =>
                    setField("max_file_mb")(Number(event.target.value))
                  }
                />
              }
            />
            <SettingRow
              title={t("Max total per message (MB)")}
              description={t(
                "Combined size of all attachments on a single message. Never below the per-file cap.",
              )}
              control={
                <input
                  className={`${inputClass} w-28`}
                  type="number"
                  min={bounds?.max_total_mb[0] ?? 1}
                  max={bounds?.max_total_mb[1] ?? 2048}
                  value={draft.max_total_mb}
                  onChange={(event) =>
                    setField("max_total_mb")(Number(event.target.value))
                  }
                />
              }
            />
          </SettingSection>

          <SettingSection
            title={t("Extraction budgets")}
            description={t(
              "Documents are converted to text and inlined into the model context. These budgets bound how much text a single file and a whole message may contribute — raise them for large documents, at the cost of context window and tokens.",
            )}
          >
            <SettingRow
              title={t("Max characters per document")}
              description={t(
                "Text extracted beyond this from one file is truncated with a notice.",
              )}
              control={
                <input
                  className={`${inputClass} w-36`}
                  type="number"
                  min={bounds?.chars[0] ?? 10000}
                  max={bounds?.chars[1] ?? 5000000}
                  step={10000}
                  value={draft.max_chars_per_doc}
                  onChange={(event) =>
                    setField("max_chars_per_doc")(Number(event.target.value))
                  }
                />
              }
            />
            <SettingRow
              title={t("Max characters per message")}
              description={t(
                "Total extracted text across all documents on one message.",
              )}
              control={
                <input
                  className={`${inputClass} w-36`}
                  type="number"
                  min={bounds?.chars[0] ?? 10000}
                  max={bounds?.chars[1] ?? 5000000}
                  step={10000}
                  value={draft.max_chars_total}
                  onChange={(event) =>
                    setField("max_chars_total")(Number(event.target.value))
                  }
                />
              }
            />
          </SettingSection>

          <p className="mt-2 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Note: images are sent to the model provider as-is — provider-side size limits still apply regardless of these caps.",
            )}
          </p>
        </>
      )}
    </div>
  );
}
