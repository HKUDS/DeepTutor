"use client";

/**
 * Compact composer for partner chat. Keeps the partner surface focused while
 * supporting the same file intake paths users expect in the main chat:
 * picker, paste, and drag/drop.
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Info, Paperclip, Square, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { shouldSubmitOnEnter } from "@/lib/composer-keyboard";
import {
  getPartnerCommands,
  type PartnerCommandInfo,
} from "@/lib/partners-api";
import {
  ATTACHMENT_ACCEPT,
  MAX_ATTACHMENT_BYTES,
  MAX_TOTAL_ATTACHMENT_BYTES,
  classifyFile,
  docIconFor,
  formatBytes,
  isSvgFilename,
} from "@/lib/doc-attachments";
import {
  extractBase64FromDataUrl,
  readFileAsDataUrl,
} from "@/lib/file-attachments";
import { useAutoSizedTextarea } from "@/lib/use-auto-sized-textarea";

export interface PartnerPendingAttachment {
  type: "image" | "file";
  filename: string;
  base64: string;
  previewUrl?: string;
  size: number;
  mimeType?: string;
}

export const PartnerComposer = memo(function PartnerComposer({
  onSend,
  onStop,
  disabled,
  streaming,
  placeholder,
}: {
  onSend: (content: string, attachments: PartnerPendingAttachment[]) => void;
  onStop?: () => void;
  disabled?: boolean;
  streaming?: boolean;
  placeholder?: string;
}) {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<PartnerPendingAttachment[]>(
    [],
  );
  const [dragging, setDragging] = useState(false);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [commands, setCommands] = useState<PartnerCommandInfo[]>([]);
  const [slashClosed, setSlashClosed] = useState(false);
  const [slashIndex, setSlashIndex] = useState(0);
  const [showHelp, setShowHelp] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const dragCounterRef = useRef(0);
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isComposingRef = useRef(false);

  useAutoSizedTextarea(textareaRef, input, { min: 24, max: 180 });

  // Slash commands (same 5 the IM channels expose) — fetched once; the palette
  // is partner-independent so no id is needed.
  useEffect(() => {
    let cancelled = false;
    void getPartnerCommands()
      .then((next) => {
        if (!cancelled) setCommands(next);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // The menu is active while the input is a bare "/word" (no space yet) and the
  // user hasn't dismissed it. Typing reopens it; Escape / accept closes it.
  const slashMatch = /^\/([a-z]*)$/i.exec(input);
  const slashQuery = slashMatch ? slashMatch[1].toLowerCase() : null;
  const slashMatches = useMemo(
    () =>
      slashQuery !== null
        ? commands.filter((c) =>
            c.command.slice(1).toLowerCase().startsWith(slashQuery),
          )
        : [],
    [commands, slashQuery],
  );
  const slashOpen = !slashClosed && slashMatches.length > 0;
  const boundedSlashIndex = Math.min(slashIndex, slashMatches.length - 1);

  const acceptCommand = useCallback((command: PartnerCommandInfo) => {
    // Arg-taking commands keep the menu out of the way with a trailing space;
    // zero-arg ones are left ready to send.
    setInput(command.arg_hint ? `${command.command} ` : command.command);
    setSlashClosed(true);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, []);

  const showAttachmentError = useCallback((message: string) => {
    setAttachmentError(message);
    if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
    errorTimerRef.current = setTimeout(() => {
      setAttachmentError(null);
      errorTimerRef.current = null;
    }, 4000);
  }, []);

  const filterFiles = useCallback(
    (files: File[]) => {
      let runningTotal = attachments.reduce((sum, item) => sum + item.size, 0);
      const accepted: File[] = [];
      const rejected: {
        name: string;
        reason: "unsupported" | "too_large" | "quota";
      }[] = [];

      for (const file of files) {
        if (!classifyFile(file)) {
          rejected.push({ name: file.name, reason: "unsupported" });
          continue;
        }
        if (file.size > MAX_ATTACHMENT_BYTES) {
          rejected.push({ name: file.name, reason: "too_large" });
          continue;
        }
        if (runningTotal + file.size > MAX_TOTAL_ATTACHMENT_BYTES) {
          rejected.push({ name: file.name, reason: "quota" });
          break;
        }
        runningTotal += file.size;
        accepted.push(file);
      }

      if (rejected.length) {
        const first = rejected[0];
        if (first.reason === "too_large") {
          showAttachmentError(
            t("File too large: {{name}}", { name: first.name }),
          );
        } else if (first.reason === "quota") {
          showAttachmentError(t("Too many files, skipped some"));
        } else {
          showAttachmentError(
            t("Unsupported file type: {{name}}", { name: first.name }),
          );
        }
      }

      return accepted;
    },
    [attachments, showAttachmentError, t],
  );

  const fileToAttachment = useCallback(
    async (file: File): Promise<PartnerPendingAttachment> => {
      const raw = await readFileAsDataUrl(file);
      const svg = isSvgFilename(file.name) || file.type === "image/svg+xml";
      const isImage = !svg && file.type.startsWith("image/");
      return {
        type: isImage ? "image" : "file",
        filename: file.name,
        base64: extractBase64FromDataUrl(raw),
        previewUrl: isImage || svg ? raw : undefined,
        size: file.size,
        mimeType: file.type || undefined,
      };
    },
    [],
  );

  const addFiles = useCallback(
    async (files: File[]) => {
      if (disabled) return;
      const accepted = filterFiles(files);
      if (!accepted.length) return;
      const next = await Promise.all(accepted.map(fileToAttachment));
      setAttachments((prev) => [...prev, ...next]);
    },
    [disabled, fileToAttachment, filterFiles],
  );

  const submit = useCallback(() => {
    const content = input.trim();
    if ((!content && attachments.length === 0) || disabled) return;
    onSend(content, attachments);
    setInput("");
    setAttachments([]);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [attachments, disabled, input, onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      // When the slash menu is open it owns the arrow/enter/tab/escape keys.
      if (slashOpen && !isComposingRef.current) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setSlashIndex((i) => Math.min(i + 1, slashMatches.length - 1));
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setSlashIndex((i) => Math.max(i - 1, 0));
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          e.preventDefault();
          acceptCommand(slashMatches[boundedSlashIndex]);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setSlashClosed(true);
          return;
        }
      }
      if (shouldSubmitOnEnter(e, isComposingRef.current)) {
        e.preventDefault();
        submit();
      }
    },
    [acceptCommand, boundedSlashIndex, slashMatches, slashOpen, submit],
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setInput(e.target.value);
      setSlashClosed(false); // typing always re-arms the menu
      setSlashIndex(0);
    },
    [],
  );

  const handlePaste = useCallback(
    async (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const files = Array.from(event.clipboardData.items)
        .filter((item) => item.kind === "file")
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null);
      if (!files.length) return;
      event.preventDefault();
      await addFiles(files);
    },
    [addFiles],
  );

  const handleDragEnter = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();
      dragCounterRef.current += 1;
      if (event.dataTransfer.types.includes("Files")) setDragging(true);
    },
    [],
  );

  const handleDragLeave = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();
      dragCounterRef.current -= 1;
      if (dragCounterRef.current <= 0) {
        dragCounterRef.current = 0;
        setDragging(false);
      }
    },
    [],
  );

  const handleDragOver = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();
    },
    [],
  );

  const handleDrop = useCallback(
    async (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();
      dragCounterRef.current = 0;
      setDragging(false);
      await addFiles(Array.from(event.dataTransfer.files));
    },
    [addFiles],
  );

  const handleFileInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const picked = Array.from(event.target.files ?? []);
      if (picked.length) void addFiles(picked);
      event.target.value = "";
    },
    [addFiles],
  );

  const removeAttachment = useCallback((index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const canSend =
    (!!input.trim() || attachments.length > 0) && !disabled && !streaming;

  return (
    <div
      className={`relative rounded-2xl border bg-[var(--card)] shadow-sm transition-colors focus-within:border-[var(--ring)] ${
        dragging
          ? "border-[var(--primary)] bg-[var(--primary)]/[0.03]"
          : "border-[var(--border)]"
      }`}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {dragging && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-2xl border-2 border-dashed border-[var(--primary)]/50 bg-[var(--primary)]/[0.04] backdrop-blur-[1px]">
          <div className="flex flex-col items-center gap-1 text-[var(--primary)]">
            <Paperclip className="h-5 w-5" strokeWidth={1.7} />
            <span className="text-[13px] font-medium">
              {t("Drop files here")}
            </span>
            <span className="text-[11px] text-[var(--primary)]/70">
              {t("Images, Office docs, code & text")}
            </span>
          </div>
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={ATTACHMENT_ACCEPT}
        onChange={handleFileInputChange}
        className="hidden"
        aria-hidden="true"
        tabIndex={-1}
      />

      {slashOpen && (
        <div className="absolute bottom-full left-0 z-20 mb-2 w-full max-w-sm overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-lg">
          {slashMatches.map((command, index) => (
            <button
              key={command.command}
              type="button"
              // onMouseDown (not onClick) so the textarea doesn't blur first.
              onMouseDown={(e) => {
                e.preventDefault();
                acceptCommand(command);
              }}
              onMouseEnter={() => setSlashIndex(index)}
              className={`flex w-full items-baseline gap-2 px-3 py-2 text-left transition-colors ${
                index === boundedSlashIndex
                  ? "bg-[var(--muted)]"
                  : "hover:bg-[var(--muted)]/60"
              }`}
            >
              <span className="font-mono text-[12.5px] text-[var(--foreground)]">
                {command.command}
              </span>
              {command.arg_hint && (
                <span className="font-mono text-[11px] text-[var(--muted-foreground)]">
                  {command.arg_hint}
                </span>
              )}
              <span className="ml-auto truncate pl-3 text-[11.5px] text-[var(--muted-foreground)]">
                {command.description}
              </span>
            </button>
          ))}
        </div>
      )}

      <textarea
        ref={textareaRef}
        value={input}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        onCompositionStart={() => {
          isComposingRef.current = true;
        }}
        onCompositionEnd={() => {
          setTimeout(() => {
            isComposingRef.current = false;
          }, 0);
        }}
        placeholder={placeholder ?? t("Type a message...")}
        rows={1}
        maxLength={32000}
        disabled={disabled || streaming}
        className="block w-full resize-none bg-transparent px-3.5 pt-3 pb-1 text-[14px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)] disabled:opacity-50"
      />

      {!!attachments.length && (
        <div className="flex flex-wrap gap-2 px-3.5 pb-2">
          {attachments.map((attachment, index) => {
            const removeLabel = t("Remove attachment");
            if (
              (attachment.type === "image" ||
                isSvgFilename(attachment.filename)) &&
              attachment.previewUrl
            ) {
              return (
                <div
                  key={`${attachment.filename}-${index}`}
                  className="group relative"
                >
                  <div className="h-14 w-14 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--muted)]/35">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={attachment.previewUrl}
                      alt={attachment.filename || t("Attachment preview")}
                      className={`h-full w-full ${isSvgFilename(attachment.filename) ? "object-contain p-1" : "object-cover"}`}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => removeAttachment(index)}
                    aria-label={removeLabel}
                    className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--foreground)] text-[var(--background)] opacity-0 shadow-sm transition-opacity group-hover:opacity-100"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </div>
              );
            }

            const spec = docIconFor(attachment.filename);
            const Icon = spec.Icon;
            return (
              <div
                key={`${attachment.filename}-${index}`}
                className="group relative"
              >
                <div className="flex h-14 w-[150px] items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 text-left">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[var(--muted)]/60">
                    <Icon size={19} strokeWidth={1.5} className={spec.tint} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[12px] font-medium text-[var(--foreground)]">
                      {attachment.filename}
                    </div>
                    <div className="truncate text-[10px] uppercase text-[var(--muted-foreground)]">
                      {spec.label} · {formatBytes(attachment.size)}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => removeAttachment(index)}
                  aria-label={removeLabel}
                  className="absolute -right-1.5 -top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--foreground)] text-[var(--background)] opacity-0 shadow-sm transition-opacity group-hover:opacity-100"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {attachmentError && (
        <div className="px-3.5 pb-2 text-[11px] text-red-600">
          {attachmentError}
        </div>
      )}

      <div className="flex items-center justify-between px-2 pb-2">
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || streaming}
            aria-label={t("Attach files")}
            title={t("Attach files")}
            className="flex h-7 w-7 items-center justify-center rounded-full text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-30"
          >
            <Paperclip className="h-4 w-4" strokeWidth={1.9} />
          </button>
          <div
            className="relative flex items-center"
            onMouseEnter={() => setShowHelp(true)}
            onMouseLeave={() => setShowHelp(false)}
          >
            <button
              type="button"
              aria-label={t("Tips")}
              className="flex h-7 w-7 items-center justify-center rounded-full text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <Info className="h-4 w-4" strokeWidth={1.9} />
            </button>
            {showHelp && (
              <div className="absolute bottom-full left-0 z-20 mb-2 w-64 rounded-xl border border-[var(--border)] bg-[var(--card)] p-3 text-[11.5px] leading-relaxed text-[var(--muted-foreground)] shadow-lg">
                <p className="mb-1 font-medium text-[var(--foreground)]">
                  {t("Tips")}
                </p>
                <p>
                  {t(
                    "Type / to see commands — start a new conversation, view history, toggle tools, and more.",
                  )}
                </p>
                <p className="mt-1.5">
                  {t(
                    "Attach images or documents with the clip, or just drag them in.",
                  )}
                </p>
              </div>
            )}
          </div>
        </div>
        {streaming ? (
          <button
            type="button"
            onClick={onStop}
            aria-label={t("Stop")}
            title={t("Stop")}
            className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--foreground)] text-[var(--background)] transition-opacity hover:opacity-90"
          >
            <Square className="h-3 w-3" strokeWidth={2.2} fill="currentColor" />
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!canSend}
            aria-label={t("Send")}
            className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-30"
          >
            <ArrowUp className="h-4 w-4" strokeWidth={2.2} />
          </button>
        )}
      </div>
    </div>
  );
});
