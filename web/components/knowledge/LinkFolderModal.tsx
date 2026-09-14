"use client";

import { useEffect, useState } from "react";
import { FolderSync } from "lucide-react";
import { useTranslation } from "react-i18next";
import Modal from "@/components/common/Modal";

interface LinkFolderModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (folderPath: string) => Promise<void>;
}

export default function LinkFolderModal({
  isOpen,
  onClose,
  onSubmit,
}: LinkFolderModalProps) {
  const { t } = useTranslation();
  const [folderPath, setFolderPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setFolderPath("");
    setError(null);
    setSubmitting(false);
  }, [isOpen]);

  const handleSubmit = async () => {
    const value = folderPath.trim();
    if (!value) {
      setError(t("Folder path is required."));
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(value);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={submitting ? () => undefined : onClose}
      title={t("Link a local folder")}
      titleIcon={<FolderSync className="h-4 w-4" />}
      width="sm"
      footer={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md px-3 py-2 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-50"
          >
            {t("Cancel")}
          </button>
          <button
            type="submit"
            form="linked-folder-form"
            disabled={submitting}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-2 text-[12px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting && (
              <span
                className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
                aria-hidden="true"
              />
            )}
            {submitting ? t("Linking…") : t("Link folder")}
          </button>
        </div>
      }
    >
      <form
        id="linked-folder-form"
        className="space-y-4 p-4"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void handleSubmit();
        }}
      >
        <div>
          <label
            htmlFor="linked-folder-path"
            className="mb-1.5 block text-[12px] font-medium text-[var(--foreground)]"
          >
            {t("Folder path")}
          </label>
          <input
            id="linked-folder-path"
            data-autofocus
            type="text"
            value={folderPath}
            required
            onChange={(event) => {
              setFolderPath(event.target.value);
              if (error) setError(null);
            }}
            onBlur={() => {
              if (!folderPath.trim()) setError(t("Folder path is required."));
            }}
            placeholder={t("e.g. /Users/name/Documents or ~/notes")}
            aria-invalid={Boolean(error)}
            aria-describedby={`linked-folder-help${error ? " linked-folder-error" : ""}`}
            className="w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-[12px] text-[var(--foreground)] outline-none transition-colors placeholder:font-sans placeholder:text-[var(--muted-foreground)] focus:border-[var(--primary)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          />
          <p
            id="linked-folder-help"
            className="mt-1.5 text-[11px] leading-relaxed text-[var(--muted-foreground)]"
          >
            {t(
              "Use a folder path on the machine running DeepTutor. Linking records the source; files are not imported until you click Sync now.",
            )}
          </p>
          {error && (
            <p
              id="linked-folder-error"
              role="alert"
              className="mt-2 rounded-md border border-red-200 bg-red-50/70 px-2.5 py-2 text-[11.5px] text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-300"
            >
              {error}
            </p>
          )}
        </div>
      </form>
    </Modal>
  );
}
