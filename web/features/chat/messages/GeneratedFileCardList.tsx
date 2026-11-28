"use client";

import { useTranslation } from "react-i18next";
import {
  GeneratedOutputFileActions,
  supportsGeneratedOutputActions,
} from "@/components/chat/GeneratedOutputFileActions";
import { ChatFileLink } from "@/components/common/ChatFileLink";
import type { MessageAttachment } from "@/features/chat/ChatStateAdapter";
import { docIconFor } from "@/lib/doc-attachments";
import { imageSrcForAttachment } from "./attachment-media";

/** Format a byte count for a file card subtitle (e.g. "14 KB"). */
function formatFileSize(bytes?: number): string {
  if (!bytes || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${units[unit]}`;
}

/** "DeepTutor_Introduction.pdf" → "DeepTutor Introduction" — the card title
 * reads like a document name; the extension already shows in the subtitle. */
function humanizeFilename(filename: string): string {
  const stem = filename.replace(/\.[A-Za-z0-9]{1,8}$/, "");
  return (
    stem
      .replace(/[_-]+/g, " ")
      .replace(/\s{2,}/g, " ")
      .trim() || filename
  );
}

export default function GeneratedFileCardList({
  files,
  onOpen,
}: {
  files: MessageAttachment[];
  onOpen?: (attachment: MessageAttachment) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="mt-3 flex flex-col gap-2">
      {files.map((a, i) => {
        const filename = a.filename || t("File");
        const key = a.workspace_item_id || a.id || a.url || `gen-${i}`;
        const mime = a.mime_type || "";
        const mediaSrc = imageSrcForAttachment(a);
        const caption = a.caption?.trim() || "";

        // Generated media renders inline; other MIME types use a file card.
        if (mime.startsWith("image/") && mediaSrc) {
          return (
            <div key={key} className="w-full max-w-[min(520px,90%)]">
              <ChatFileLink
                attachment={a}
                onOpen={onOpen}
                className="group block w-full overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] text-left shadow-sm transition hover:border-[var(--border)]"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={mediaSrc}
                  alt={filename}
                  loading="lazy"
                  className="block max-h-[360px] w-full bg-[var(--background)] object-contain"
                />
                <span className="flex items-center justify-between gap-2 px-3 py-2">
                  <span className="min-w-0">
                    <span className="block truncate text-[12.5px] font-medium text-[var(--foreground)]">
                      {a.title || humanizeFilename(filename)}
                    </span>
                    {caption ? (
                      <span className="block truncate text-[11px] text-[var(--muted-foreground)]">
                        {caption}
                      </span>
                    ) : null}
                  </span>
                  <span className="shrink-0 text-[11px] text-[var(--muted-foreground)] transition group-hover:text-[var(--foreground)]">
                    {t("Open")}
                  </span>
                </span>
              </ChatFileLink>
              {supportsGeneratedOutputActions(a) ? (
                <GeneratedOutputFileActions url={a.url || ""} />
              ) : null}
            </div>
          );
        }

        if (mime.startsWith("video/") && mediaSrc) {
          return (
            <div
              key={key}
              className="w-full max-w-[min(520px,90%)] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-sm"
            >
              <video
                src={mediaSrc}
                controls
                preload="metadata"
                className="block max-h-[360px] w-full bg-black"
              />
              <ChatFileLink
                attachment={a}
                onOpen={onOpen}
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left transition hover:bg-[var(--muted)]/30"
              >
                <span className="min-w-0">
                  <span className="block truncate text-[12.5px] font-medium text-[var(--foreground)]">
                    {a.title || humanizeFilename(filename)}
                  </span>
                  {caption ? (
                    <span className="block truncate text-[11px] text-[var(--muted-foreground)]">
                      {caption}
                    </span>
                  ) : null}
                </span>
                <span className="shrink-0 text-[11px] text-[var(--muted-foreground)]">
                  {t("Open")}
                </span>
              </ChatFileLink>
              {supportsGeneratedOutputActions(a) ? (
                <GeneratedOutputFileActions url={a.url || ""} />
              ) : null}
            </div>
          );
        }

        const spec = docIconFor(filename);
        const Icon = spec.Icon;
        const size = formatFileSize(a.size_bytes);
        return (
          <div key={key} className="w-full max-w-[min(520px,90%)]">
            <ChatFileLink
              attachment={a}
              onOpen={onOpen}
              className="group flex w-full items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-left shadow-sm transition hover:border-[var(--border)] hover:bg-[var(--muted)]/30"
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--background)]">
                <Icon className={`h-[18px] w-[18px] ${spec.tint}`} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium text-[var(--foreground)]">
                  {a.title || humanizeFilename(filename)}
                </span>
                <span className="block text-[11px] text-[var(--muted-foreground)]">
                  {caption || spec.label}
                  {size ? ` · ${size}` : ""}
                </span>
              </span>
              <span className="shrink-0 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--foreground)] transition group-hover:bg-[var(--muted)]/40">
                {t("Open")}
              </span>
            </ChatFileLink>
            {supportsGeneratedOutputActions(a) ? (
              <GeneratedOutputFileActions url={a.url || ""} />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
