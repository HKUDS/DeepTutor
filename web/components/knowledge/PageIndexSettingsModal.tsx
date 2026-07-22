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

const DEFAULT_BASE_URL = "https://api.pageindex.ai";

interface PageIndexSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Called after a successful save so callers can refresh provider state. */
  onSaved?: () => void;
}

export default function PageIndexSettingsModal({
  isOpen,
  onClose,
  onSaved,
}: PageIndexSettingsModalProps) {
  const { t } = useTranslation();
  const [config, setConfig] = useState<PageIndexConfig | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setApiKey("");
    getPageIndexConfig({ force: true })
      .then((cfg) => {
        if (cancelled) return;
        setConfig(cfg);
        setBaseUrl(cfg.api_base_url || "");
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  const persist = async (payload: {
    api_key?: string;
    api_base_url?: string;
  }) => {
    setSaving(true);
    setError(null);
    try {
      const next = await updatePageIndexConfig(payload);
      setConfig(next);
      setApiKey("");
      onSaved?.();
      return next;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    // Blank key keeps the stored one; a typed value replaces it.
    const payload: { api_key?: string; api_base_url?: string } = {
      api_base_url: baseUrl.trim() || undefined,
    };
    if (apiKey.trim()) payload.api_key = apiKey.trim();
    const next = await persist(payload);
    if (next) onClose();
  };

  const keySet = config?.api_key_set ?? false;

  return (
    <Modal
      isOpen={isOpen}
      onClose={saving ? () => {} : onClose}
      title={t("PageIndex settings")}
      titleIcon={<KeyRound size={16} />}
      width="md"
      closeOnBackdrop={!saving}
      closeOnEscape={!saving}
      footer={
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
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="rounded-md px-3 py-1.5 text-[12.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
            >
              {t("Cancel")}
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving || loading}
              className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {t("Save")}
            </button>
          </div>
        </div>
      }
    >
      <div className="space-y-4 px-5 py-4">
        <p className="text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
          {t(
            "PageIndex is a hosted, vectorless retrieval engine. Documents in a PageIndex knowledge base are uploaded to PageIndex's servers for processing. One key is shared by all your PageIndex knowledge bases.",
          )}
        </p>

        {loading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : (
          <>
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

            <div>
              <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                {t("API base URL")}
              </label>
              <input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                disabled={saving}
                placeholder={DEFAULT_BASE_URL}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
              />
            </div>
          </>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
            {error}
          </div>
        )}
      </div>
    </Modal>
  );
}
