"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ExternalLink, KeyRound, Loader2 } from "lucide-react";
import Modal from "@/components/common/Modal";
import {
  getPageIndexConfig,
  updatePageIndexConfig,
  type PageIndexConfig,
} from "@/lib/knowledge-api";

interface PageIndexSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Called after a successful save so callers can refresh provider state. */
  onSaved?: () => void;
}

interface PageIndexConfigFormProps {
  onChanged?: () => void;
  onSubmit?: () => void;
  onCancel?: () => void;
  onError?: (message: string) => void;
  onSavingChange?: (saving: boolean) => void;
}

export function PageIndexConfigForm({
  onChanged,
  onSubmit,
  onCancel,
  onError,
  onSavingChange,
}: PageIndexConfigFormProps) {
  const { t } = useTranslation();
  const [config, setConfig] = useState<PageIndexConfig | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPageIndexConfig({ force: true })
      .then((next) => {
        if (!cancelled) setConfig(next);
      })
      .catch((err) => {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        onError?.(message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // The form intentionally loads once when it is mounted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const persist = async (payload: { api_key?: string }) => {
    setSaving(true);
    onSavingChange?.(true);
    setError(null);
    try {
      const next = await updatePageIndexConfig(payload);
      setConfig(next);
      setApiKey("");
      onChanged?.();
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      onError?.(message);
      return false;
    } finally {
      setSaving(false);
      onSavingChange?.(false);
    }
  };

  const save = async () => {
    const payload = apiKey.trim() ? { api_key: apiKey.trim() } : {};
    if (await persist(payload)) onSubmit?.();
  };

  const keySet = config?.api_key_set ?? false;
  const modal = Boolean(onCancel);

  return (
    <div
      className={
        modal
          ? "space-y-4 px-5 py-4"
          : "space-y-4 rounded-2xl border border-[var(--border)] p-4"
      }
    >
      <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
        {t(
          "PageIndex is a hosted, vectorless retrieval engine. Documents in a PageIndex knowledge base are uploaded to PageIndex's servers for processing. One key is shared by all your PageIndex knowledge bases.",
        )}
      </p>

      {loading ? (
        <div className="flex items-center justify-center py-6">
          <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : (
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("API key")}
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            disabled={saving}
            placeholder={
              keySet
                ? t("•••••••• (configured — leave blank to keep)")
                : t("Enter your PageIndex API key")
            }
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
          />
          {keySet && (
            <button
              type="button"
              onClick={() => void persist({ api_key: "" })}
              disabled={saving}
              className="mt-1.5 text-[11px] font-medium text-red-600 transition-colors hover:text-red-700 disabled:opacity-40 dark:text-red-400"
            >
              {t("Remove stored key")}
            </button>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between gap-2">
        <a
          href="https://dash.pageindex.ai/api-keys"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-[11.5px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          {t("Get an API key")}
          <ExternalLink className="h-3 w-3" />
        </a>
        <div className="flex items-center gap-2">
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              disabled={saving}
              className="rounded-md px-3 py-1.5 text-[12.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              {t("Cancel")}
            </button>
          )}
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving || loading}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {t(modal ? "Save" : "Save changes")}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function PageIndexSettingsModal({
  isOpen,
  onClose,
  onSaved,
}: PageIndexSettingsModalProps) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);

  return (
    <Modal
      isOpen={isOpen}
      onClose={saving ? () => {} : onClose}
      title={t("PageIndex settings")}
      titleIcon={<KeyRound size={16} />}
      width="md"
      closeOnBackdrop={!saving}
      closeOnEscape={!saving}
    >
      {isOpen && (
        <PageIndexConfigForm
          onChanged={onSaved}
          onSubmit={onClose}
          onCancel={onClose}
          onSavingChange={setSaving}
        />
      )}
    </Modal>
  );
}
