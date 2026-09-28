"use client";

import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, FileSpreadsheet, Loader2, X } from "lucide-react";
import {
  commitPracticeImport,
  downloadPracticeTemplate,
  previewPracticeImport,
  type ImportPreview,
} from "@/lib/practice-api";

export function PracticeImport({
  onClose,
  onImported,
  initialTarget,
  courseId = "",
}: {
  onClose: () => void;
  onImported: (message: string) => void;
  initialTarget: "bank" | "mistakes";
  courseId?: string;
}) {
  const { t } = useTranslation();
  const [target, setTarget] = useState(initialTarget);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [filename, setFilename] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState("");
  async function select(file?: File) {
    if (!file || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    setPreview(null);
    setFilename(file.name);
    try {
      setPreview(await previewPracticeImport(file, target, courseId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  async function commit() {
    if (!preview?.token || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await commitPracticeImport(preview.token);
      onImported(t("Imported {{created}} questions; skipped {{duplicates}} duplicates.", result));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <section
      aria-labelledby="practice-import-title"
      className="mb-6 rounded-2xl border border-border bg-card p-5 sm:p-6"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="practice-import-title" className="flex items-center gap-2 text-base font-semibold">
          <FileSpreadsheet size={18} />
          {t("Import questions")}
        </h2>
        <button
          type="button"
          onClick={onClose}
          disabled={busy}
          aria-label={t("Close import")}
          className="rounded-lg p-2 hover:bg-muted disabled:opacity-50"
        >
          <X size={17} />
        </button>
      </div>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        {t(
          "Import XLSX, CSV, TSV or JSON. Up to 500 questions and 5 MB per file. XLSX uses the active sheet. Chinese and English column names are supported.",
        )}
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          {t("Import into")}
          <select
            value={target}
            disabled={busy}
            onChange={event => {
              setTarget(event.target.value as typeof target);
              setPreview(null);
              setFilename("");
            }}
            className="rounded-lg border border-border bg-background p-2"
          >
            <option value="bank">{t("Question Bank")}</option>
            <option value="mistakes">{t("Mistakes")}</option>
          </select>
        </label>
        {(["xlsx", "csv"] as const).map(format => (
          <button
            key={format}
            type="button"
            onClick={() => {
              void downloadPracticeTemplate(format).catch(err => setError(String(err)));
            }}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs hover:bg-muted"
          >
            <Download size={14} />
            {t("Download {{format}} template", { format: format.toUpperCase() })}
          </button>
        ))}
      </div>
      <label className="mt-4 block rounded-xl border border-dashed border-border bg-muted/20 p-5 text-sm">
        <span className="mb-2 block font-medium">{t("Choose a question file")}</span>
        <input
          key={target}
          type="file"
          accept=".xlsx,.csv,.tsv,.json"
          disabled={busy}
          onChange={event => {
            void select(event.target.files?.[0]);
            event.target.value = "";
          }}
          className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-primary/10 file:px-3 file:py-2 file:text-primary"
        />
        <span className="mt-2 block text-xs text-muted-foreground">
          {t(
            "Question and answer are required. Use tags to organize imported questions. Review the preview before saving.",
          )}
        </span>
      </label>
      {busy && (
        <p role="status" className="mt-3 flex items-center gap-2 text-sm">
          <Loader2 size={16} className="animate-spin" />
          {t("Processing…")}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      )}
      {preview && (
        <div className="mt-4 space-y-3">
          <p className="break-all text-sm font-medium">
            {filename} ·{" "}
            {t("{{valid}} of {{total}} rows are valid", {
              valid: preview.valid,
              total: preview.total,
            })}
          </p>
          {preview.errors.length > 0 && (
            <div
              role="alert"
              className="max-h-40 overflow-auto rounded-lg bg-destructive/5 p-3 text-sm text-destructive"
            >
              <p className="mb-2 font-medium">
                {t("Nothing has been imported. Fix these rows and select the file again.")}
              </p>
              {preview.errors.map(error => (
                <p key={error.row}>
                  {t("Row {{row}}", { row: error.row })}: {error.message}
                </p>
              ))}
            </div>
          )}
          <ol className="divide-y divide-border rounded-lg border border-border px-3">
            {preview.samples.map((question, index) => (
              <li key={index} className="py-3 text-sm">
                <p className="line-clamp-2">{question.question}</p>
                <p className="mt-1 truncate text-xs text-muted-foreground">
                  {t("Correct answer")}: {question.correct_answer}
                  {question.tags.length ? ` · ${question.tags.join(" / ")}` : ""}
                </p>
              </li>
            ))}
          </ol>
          <p className="text-xs text-muted-foreground">
            {t(
              "Existing questions are kept. Identical imports are skipped and their tags are combined.",
            )}
          </p>
          <button
            type="button"
            disabled={busy || !preview.token}
            onClick={() => void commit()}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-40"
          >
            {t("Confirm import")}
          </button>
        </div>
      )}
    </section>
  );
}
