"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Languages, Loader2, CheckCircle2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import Modal from "@/components/common/Modal";
import {
  bilingualApi,
  immersiveReadingApi,
  type BilingualPairing,
  type ReadingDocument,
} from "@/lib/immersive-reading-api";

interface BilingualPairDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onPaired: (pairing: BilingualPairing) => void;
}

export function BilingualPairDialog({ isOpen, onClose, onPaired }: BilingualPairDialogProps) {
  const { t } = useTranslation();
  const [documents, setDocuments] = useState<ReadingDocument[]>([]);
  const [enId, setEnId] = useState("");
  const [zhId, setZhId] = useState("");
  const [targetLang, setTargetLang] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (isOpen) {
      immersiveReadingApi.list().then((data) => {
        setDocuments(data.documents);
      });
      setError("");
    }
  }, [isOpen]);

  const handlePair = useCallback(async () => {
    if (!enId || !zhId) {
      setError(t("Select both an English and a Chinese book."));
      return;
    }
    if (enId === zhId) {
      setError(t("English and Chinese books must be different."));
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await bilingualApi.pair(enId, zhId, targetLang || undefined);
      // Auto-align immediately.
      await bilingualApi.align(result.pairing_id);
      const updated = await bilingualApi.get(result.pairing_id);
      onPaired(updated);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [enId, zhId, targetLang, onPaired, onClose, t]);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={t("Pair Bilingual Books")}
      titleIcon={<Languages size={18} />}
      width="md"
      footer={
        <div className="flex items-center justify-between">
          {error && (
            <span className="flex items-center gap-1 text-sm text-[var(--destructive)]">
              <AlertCircle size={15} />
              {error}
            </span>
          )}
          <div className="ml-auto flex gap-2">
            <button
              onClick={onClose}
              className="rounded-lg px-3 py-1.5 text-sm text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            >
              {t("Cancel")}
            </button>
            <button
              onClick={handlePair}
              disabled={loading || !enId || !zhId}
              className="flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 py-1.5 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
            >
              {loading ? <Loader2 size={15} className="animate-spin" /> : <Languages size={15} />}
              {t("Pair & Align")}
            </button>
          </div>
        </div>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-[var(--muted-foreground)]">
          {t("Select an English book as the primary text and a Chinese translation. The Chinese will appear as expandable panels.")}
        </p>
        <div className="space-y-2">
          <label className="text-sm font-medium">{t("English Book (primary)")}</label>
          <select
            value={enId}
            onChange={(e) => setEnId(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
          >
            <option value="">{t("Select...")}</option>
            {documents.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.title}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium">{t("Chinese Translation")}</label>
          <select
            value={zhId}
            onChange={(e) => setZhId(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
          >
            <option value="">{t("Select...")}</option>
            {documents.map((doc) => (
              <option key={doc.id} value={doc.id}>
                {doc.title}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium">{t("Chinese Variant")}</label>
          <select
            value={targetLang}
            onChange={(e) => setTargetLang(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
          >
            <option value="">{t("Auto-detect")}</option>
            <option value="zh-Hant">{t("Traditional (繁體)")}</option>
            <option value="zh-Hans">{t("Simplified (简体)")}</option>
          </select>
        </div>
        {documents.length < 2 && (
          <p className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
            <AlertCircle size={14} />
            {t("Import at least two books first (one English, one Chinese).")}
          </p>
        )}
      </div>
    </Modal>
  );
}

export function BilingualPairingCard({
  pairing,
  onOpen,
  onDelete,
}: {
  pairing: BilingualPairing;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-3">
      <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[var(--primary)]/10">
        <Languages size={20} className="text-[var(--primary)]" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{pairing.en_title}</p>
        <p className="truncate text-xs text-[var(--muted-foreground)]">
          {pairing.zh_title} · {pairing.chapter_count} {t("chapters")}
        </p>
      </div>
      {pairing.aligned ? (
        <span className="flex items-center gap-1 text-xs text-[var(--muted-foreground)]">
          <CheckCircle2 size={14} className="text-green-500" />
          {t("Aligned")}
        </span>
      ) : (
        <span className="text-xs text-[var(--muted-foreground)]">{t("Not aligned")}</span>
      )}
      <button
        onClick={onOpen}
        className="rounded-lg bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] hover:opacity-90"
      >
        {t("Read")}
      </button>
      <button
        onClick={onDelete}
        className="rounded-lg px-2 py-1.5 text-xs text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
      >
        {t("Delete")}
      </button>
    </div>
  );
}
