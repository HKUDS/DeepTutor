"use client";

import { useCallback, useMemo, useRef, useState, type DragEvent } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, CheckCircle2, FileText, Files, X } from "lucide-react";
import type { KnowledgeUploadPolicy } from "@/lib/knowledge-api";
import {
  formatFileSize,
  mergeSelectedFiles,
  selectionFileId,
  validateFiles,
  type ValidatedFileSelection,
} from "@/lib/knowledge-helpers";

interface DropState {
  active: boolean;
  invalid: boolean;
  draggedCount: number;
}

const EMPTY_DROP_STATE: DropState = {
  active: false,
  invalid: false,
  draggedCount: 0,
};

interface FileDropZoneProps {
  files: File[];
  onChange: (files: File[]) => void;
  uploadPolicy: KnowledgeUploadPolicy;
  disabled?: boolean;
  compact?: boolean;
  hidePolicyHint?: boolean;
}

export default function FileDropZone({
  files,
  onChange,
  uploadPolicy,
  disabled = false,
  compact = false,
  hidePolicyHint = false,
}: FileDropZoneProps) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const dirInputRef = useRef<HTMLInputElement>(null);
  const depthRef = useRef(0);
  const [dropState, setDropState] = useState<DropState>(EMPTY_DROP_STATE);

  // `webkitdirectory`/`directory` are non-standard attrs (not in React's
  // typings) but widely supported — set them imperatively to pick a folder.
  const setDirInput = useCallback((el: HTMLInputElement | null) => {
    dirInputRef.current = el;
    if (el) {
      el.setAttribute("webkitdirectory", "");
      el.setAttribute("directory", "");
    }
  }, []);

  const selection = useMemo<ValidatedFileSelection>(
    () => validateFiles(files, uploadPolicy, t),
    [files, uploadPolicy, t],
  );

  const previewDropped = useCallback(
    (incoming: File[]) => {
      const validated = validateFiles(incoming, uploadPolicy, t);
      return {
        count: incoming.length,
        invalid: validated.invalidFiles.length > 0,
      };
    },
    [t, uploadPolicy],
  );

  const reset = useCallback(() => {
    depthRef.current = 0;
    setDropState(EMPTY_DROP_STATE);
  }, []);

  const handleEnter = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (disabled) return;
      if (!Array.from(event.dataTransfer.types).includes("Files")) return;
      event.preventDefault();
      event.stopPropagation();
      depthRef.current += 1;
      const incoming = Array.from(event.dataTransfer.items)
        .filter((item) => item.kind === "file")
        .map((item) => item.getAsFile())
        .filter((file): file is File => Boolean(file));
      const preview = previewDropped(incoming);
      setDropState({
        active: true,
        invalid: preview.invalid,
        draggedCount: preview.count,
      });
    },
    [disabled, previewDropped],
  );

  const handleOver = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (disabled) return;
      if (!Array.from(event.dataTransfer.types).includes("Files")) return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "copy";
      const incoming = Array.from(event.dataTransfer.items)
        .filter((item) => item.kind === "file")
        .map((item) => item.getAsFile())
        .filter((file): file is File => Boolean(file));
      const preview = previewDropped(incoming);
      setDropState({
        active: true,
        invalid: preview.invalid,
        draggedCount: preview.count,
      });
    },
    [disabled, previewDropped],
  );

  const handleLeave = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (disabled) return;
      if (!Array.from(event.dataTransfer.types).includes("Files")) return;
      event.preventDefault();
      event.stopPropagation();
      depthRef.current = Math.max(0, depthRef.current - 1);
      if (depthRef.current === 0) reset();
    },
    [disabled, reset],
  );

  const handleDrop = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (disabled) return;
      if (!Array.from(event.dataTransfer.types).includes("Files")) return;
      event.preventDefault();
      event.stopPropagation();
      const dropped = Array.from(event.dataTransfer.files || []);
      reset();
      if (!dropped.length) return;
      onChange(mergeSelectedFiles(files, dropped));
    },
    [disabled, files, onChange, reset],
  );

  const removeFile = useCallback(
    (id: string) => {
      onChange(files.filter((file) => selectionFileId(file) !== id));
    },
    [files, onChange],
  );

  const clearAll = useCallback(() => {
    onChange([]);
    if (inputRef.current) inputRef.current.value = "";
  }, [onChange]);

  const padding = compact ? "px-4 py-5" : "px-5 py-7";

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragEnter={handleEnter}
        onDragLeave={handleLeave}
        onDragOver={handleOver}
        onDrop={handleDrop}
        disabled={disabled}
        className={`group flex w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed text-center transition-colors ${padding} ${
          dropState.active
            ? dropState.invalid
              ? "border-amber-400 bg-amber-50/60 dark:border-amber-700 dark:bg-amber-950/20"
              : "border-sky-400 bg-sky-50/60 dark:border-sky-700 dark:bg-sky-950/20"
            : "border-[var(--border)] bg-[var(--background)] hover:border-[var(--foreground)]/25 hover:bg-[var(--muted)]/40"
        } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
      >
        <Files className="h-5 w-5 text-[var(--muted-foreground)] transition-colors group-hover:text-[var(--foreground)]" />
        <div className="space-y-1">
          <div className="text-[13px] font-medium text-[var(--foreground)]">
            {dropState.active
              ? dropState.invalid
                ? t("Some dragged files are not supported")
                : t("Drop files to add them")
              : files.length
                ? selection.invalidFiles.length > 0
                  ? t("{{count}} invalid files", {
                      count: selection.invalidFiles.length,
                    })
                  : t("{{count}} files ready", {
                      count: selection.validFiles.length,
                    })
                : t("Choose files...")}
          </div>
          <p className="text-[11px] text-[var(--muted-foreground)]">
            {dropState.active
              ? dropState.draggedCount > 0
                ? t("{{count}} files detected", {
                    count: dropState.draggedCount,
                  })
                : t("Release to attach the files")
              : files.length
                ? formatFileSize(selection.totalBytes)
                : t("Click to browse supported documents")}
          </p>
        </div>
      </button>

      {!disabled && (
        <button
          type="button"
          onClick={() => dirInputRef.current?.click()}
          className="text-[11px] font-medium text-[var(--muted-foreground)] underline-offset-2 transition-colors hover:text-[var(--foreground)] hover:underline"
        >
          {t("Or select an entire folder")}
        </button>
      )}

      {!hidePolicyHint && (
        <p className="text-[11px] text-[var(--muted-foreground)]">
          {uploadPolicy.extensions.length} {t("types")} ·{" "}
          {t("Maximum file size: {{size}}", {
            size: formatFileSize(uploadPolicy.max_file_size_bytes),
          })}
        </p>
      )}

      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        accept={uploadPolicy.accept}
        onChange={(event) => {
          const picked = Array.from(event.target.files || []);
          event.target.value = "";
          onChange(mergeSelectedFiles(files, picked));
        }}
      />

      {/* Directory picker — files carry webkitRelativePath so the upload keeps
          the folder structure. Unsupported members are flagged, not blocked. */}
      <input
        ref={setDirInput}
        type="file"
        multiple
        className="hidden"
        onChange={(event) => {
          const picked = Array.from(event.target.files || []);
          event.target.value = "";
          onChange(mergeSelectedFiles(files, picked));
        }}
      />

      {selection.items.length > 0 && (
        <SelectionSummary
          selection={selection}
          onRemove={removeFile}
          onClear={clearAll}
        />
      )}
    </div>
  );
}

function SelectionSummary({
  selection,
  onRemove,
  onClear,
}: {
  selection: ValidatedFileSelection;
  onRemove: (id: string) => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const invalidCount = selection.invalidFiles.length;
  const readyCount = selection.validFiles.length;
  const hasIssues = invalidCount > 0;

  return (
    <div
      className={`rounded-2xl border p-3 ${
        hasIssues
          ? "border-amber-200 bg-amber-50/80 dark:border-amber-900/70 dark:bg-amber-950/20"
          : "border-emerald-200 bg-emerald-50/70 dark:border-emerald-900/60 dark:bg-emerald-950/15"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[13px] font-medium text-[var(--foreground)]">
            {hasIssues ? (
              <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
            ) : (
              <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
            )}
            {hasIssues
              ? t("{{ready}} ready, {{skip}} will be skipped", {
                  ready: readyCount,
                  skip: invalidCount,
                })
              : t("{{count}} files ready", { count: readyCount })}
          </div>
          <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
            {hasIssues
              ? t("Unsupported files are skipped; the rest will be indexed.")
              : t("Ready to upload")}{" "}
            · {formatFileSize(selection.totalBytes)}
          </p>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="rounded-md border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)] hover:text-[var(--foreground)]"
        >
          {t("Clear selection")}
        </button>
      </div>

      <div className="mt-3 space-y-2">
        {selection.items.map((item) => (
          <div
            key={item.id}
            className={`flex items-start gap-3 rounded-xl border px-3 py-2.5 ${
              item.valid
                ? "border-white/60 bg-white/70 dark:border-white/10 dark:bg-white/5"
                : "border-amber-200/80 bg-amber-100/60 dark:border-amber-900/60 dark:bg-amber-950/20"
            }`}
          >
            <div
              className={`mt-0.5 rounded-lg p-2 ${
                item.valid
                  ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300"
                  : "bg-amber-100 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300"
              }`}
            >
              <FileText className="h-3.5 w-3.5" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[12px] font-medium text-[var(--foreground)]">
                {item.file.name}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
                <span>{item.extension}</span>
                <span>{item.sizeLabel}</span>
                <span
                  className={`rounded-full px-2 py-0.5 normal-case tracking-normal ${
                    item.valid
                      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300"
                      : "bg-amber-100 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300"
                  }`}
                >
                  {item.valid ? t("Supported") : t("Needs attention")}
                </span>
              </div>
              {item.error && (
                <p className="mt-1.5 text-[11px] leading-relaxed text-amber-700 dark:text-amber-300">
                  {item.error}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={() => onRemove(item.id)}
              title={t("Remove")}
              className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)] hover:text-[var(--foreground)]"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
