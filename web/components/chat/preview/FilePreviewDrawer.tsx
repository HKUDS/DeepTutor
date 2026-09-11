"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { BookOpenText, Check, Copy, Download, Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { docIconFor, formatBytes } from "@/lib/doc-attachments";
import { apiUrl } from "@/lib/api";
import { apiFetch } from "@/lib/api";
import { uploadMaterial } from "@/lib/reading-api";
import { createReadingWorkspace } from "@/lib/reading-workspace-api";
import {
  type FilePreviewSource,
  previewKindFor,
  resolveSourceUrl,
} from "./previewerFor";

// Heavy renderers are lazy so opening the drawer with a small image doesn't
// pay the cost of loading the markdown / code-highlight chunks.
const PdfPreview = dynamic(() => import("./previewers/PdfPreview"));
const ImagePreview = dynamic(() => import("./previewers/ImagePreview"));
const VideoPreview = dynamic(() => import("./previewers/VideoPreview"));
const SvgPreview = dynamic(() => import("./previewers/SvgPreview"));
const MarkdownPreview = dynamic(() => import("./previewers/MarkdownPreview"));
const TextPreview = dynamic(() => import("./previewers/TextPreview"));
const DocxPreview = dynamic(() => import("./previewers/DocxPreview"));
const XlsxPreview = dynamic(() => import("./previewers/XlsxPreview"));
const OfficeTextPreview = dynamic(
  () => import("./previewers/OfficeTextPreview"),
);
const FallbackPreview = dynamic(() => import("./previewers/FallbackPreview"));

const ANIM_MS = 220;

interface FilePreviewDrawerProps {
  open: boolean;
  source: FilePreviewSource | null;
  onClose: () => void;
}

/**
 * Right-side slide-in drawer that previews a chat attachment.
 *
 * Design notes
 * ────────────
 * • No backdrop. The drawer sits alongside the chat so the user can still
 *   read messages or send replies — closer to Claude desktop's "side panel"
 *   than a modal dialog.
 * • The shell is **always mounted**, parked off-screen at translate-x-full.
 *   That way every open is a single class flip and CSS handles the rest —
 *   no double-render, no requestAnimationFrame dance, no delay before the
 *   slide starts. Only the body content (header + preview) is conditionally
 *   rendered, latched during the exit transition so it doesn't tear.
 * • Renderers are lazy so opening a small image doesn't drag in markdown /
 *   syntax-highlight chunks.
 */
export default function FilePreviewDrawer({
  open,
  source,
  onClose,
}: FilePreviewDrawerProps) {
  const { t } = useTranslation();
  const router = useRouter();

  // Latch the most recently shown source so the body keeps rendering during
  // the slide-out transition.
  const [renderedSource, setRenderedSource] =
    useState<FilePreviewSource | null>(null);
  // The HEAVY preview body (markdown / syntax-highlight) is gated on this
  // flag and only mounts AFTER the slide-in finishes. The chat-page's
  // padding-right transition lives on the main thread, and so does
  // react-markdown's reconciliation — if both run at once, the markdown
  // work eats every frame and the chat squeeze visibly stalls. Deferring
  // the body keeps the main thread free for the slide animations.
  const [bodyMounted, setBodyMounted] = useState(false);
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  // Mirror `source` synchronously DURING render. React commits a single
  // render where both `renderedSource` and the outer slide class flip
  // together — that single paint also fires the chat-page's padding
  // transition, so the drawer slide and the chat squeeze launch in
  // lock-step (no one-frame gap from a useEffect-driven latch).
  //
  // We also reset `bodyMounted` here so a switch to a new source doesn't
  // momentarily render the heavy body before the deferring effect kicks in.
  if (open && source && source !== renderedSource) {
    setRenderedSource(source);
    setBodyMounted(false);
  }

  // After close, defer the body unmount until the slide-out animation has
  // had time to play. The cleanup cancels the pending unmount if the user
  // re-opens before it fires.
  useEffect(() => {
    if (!open && renderedSource) {
      const timer = setTimeout(() => setRenderedSource(null), ANIM_MS);
      return () => clearTimeout(timer);
    }
  }, [open, renderedSource]);

  // After the slide-in completes, mount the heavy body. Done in an effect
  // so the timer is scoped to the open lifecycle (cleanup cancels it if
  // the user closes before it fires).
  useEffect(() => {
    if (open && renderedSource && !bodyMounted) {
      const timer = setTimeout(() => setBodyMounted(true), ANIM_MS);
      return () => clearTimeout(timer);
    }
  }, [open, renderedSource, bodyMounted]);

  // `visible` derives directly from `open`, so it flips in the very same
  // render where the parent's `previewSource` flipped — same instant the
  // chat's padding-right transition starts.
  const visible = open;

  // Focus the close button on open so keyboard users can immediately ESC.
  useEffect(() => {
    if (visible) closeBtnRef.current?.focus();
  }, [visible]);

  // ESC closes (only while visible — listening on document is fine since the
  // drawer is global).
  useEffect(() => {
    if (!visible) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [visible, onClose]);

  const previewUrl = renderedSource
    ? resolveSourceUrl(renderedSource, apiUrl)
    : null;
  const downloadUrl = previewUrl;
  const previewKind = renderedSource ? previewKindFor(renderedSource) : null;

  const [copied, setCopied] = useState(false);
  const [openingInReader, setOpeningInReader] = useState(false);
  const [readerError, setReaderError] = useState("");
  const handleCopy = useCallback(async () => {
    if (!downloadUrl) return;
    try {
      await navigator.clipboard.writeText(downloadUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard rejected (insecure context / permission). Silently noop —
      // the user can still right-click the download link.
    }
  }, [downloadUrl]);

  const canOpenInReading = renderedSource
    ? /\.(pdf|epub|ppt|pptx|doc|docx|txt|md|markdown|html?|mp3|wav|m4a|aac|ogg|mp4|mov|m4v|webm|mkv)$/i.test(
        renderedSource.filename,
      )
    : false;

  const handleOpenInReading = useCallback(async () => {
    if (!renderedSource || !previewUrl || openingInReader) return;
    setOpeningInReader(true);
    setReaderError("");
    try {
      const response =
        previewUrl.startsWith("data:") || previewUrl.startsWith("blob:")
          ? await fetch(previewUrl)
          : await apiFetch(previewUrl, { cache: "no-store" });
      if (!response.ok)
        throw new Error(t("The attachment could not be downloaded."));
      const blob = await response.blob();
      const file = new File([blob], renderedSource.filename, {
        type: renderedSource.mimeType || blob.type,
      });
      const material = await uploadMaterial(file);
      const workspace = await createReadingWorkspace({
        title:
          material.title || renderedSource.filename.replace(/\.[^.]+$/, ""),
        material_ids: [material.material_id],
      });
      onClose();
      router.push(`/reading/${workspace.workspace_id}`);
    } catch (caught) {
      setReaderError(
        caught instanceof Error
          ? caught.message
          : t("The attachment could not be opened in Immersive Reading."),
      );
    } finally {
      setOpeningInReader(false);
    }
  }, [onClose, openingInReader, previewUrl, renderedSource, router, t]);

  const filename = renderedSource?.filename || t("Attachment");
  const spec = docIconFor(filename);
  const HeaderIcon = spec.Icon;
  const sizeLabel = renderedSource?.size
    ? formatBytes(renderedSource.size)
    : "";

  return (
    <div
      role="dialog"
      aria-hidden={!visible}
      aria-label={t("File preview: {{name}}", { name: filename })}
      // Full-screen sheet below the drawer breakpoint, matching
      // SessionViewerPanel — a 92vw overlay on a phone is an awkward
      // near-miss rather than a usable second column.
      className={`fixed right-0 top-0 z-[30] flex h-dvh w-full flex-col border-l border-[var(--border)] bg-[var(--card)] transition-transform ease-out md:w-[min(560px,92vw)] ${
        // shadow-2xl only while visible — parked off-screen at translate-x-full,
        // the blurred shadow still bleeds ~38px back onto the viewport's right
        // edge. Dropping it off-screen kills that stray sliver.
        visible ? "translate-x-0 shadow-2xl" : "translate-x-full"
      }`}
      style={{
        // Hand the transform to the GPU compositor for a buttery slide.
        willChange: "transform",
        transitionDuration: `${ANIM_MS}ms`,
        // While off-screen the drawer must not steal pointer events from
        // the chat behind it.
        pointerEvents: visible ? "auto" : "none",
      }}
    >
      {renderedSource && (
        <>
          {/* Header */}
          <div className="flex items-center gap-2 border-b border-[var(--border)] bg-[var(--card)] px-4 py-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[var(--muted)]/60">
              <HeaderIcon size={18} strokeWidth={1.5} className={spec.tint} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-medium text-[var(--foreground)]">
                {filename}
              </div>
              <div className="truncate text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
                {sizeLabel ? `${spec.label} · ${sizeLabel}` : spec.label}
              </div>
            </div>

            {canOpenInReading && downloadUrl && (
              <button
                type="button"
                onClick={() => void handleOpenInReading()}
                disabled={openingInReader}
                title={t("Open in Immersive Reading")}
                className="mr-1 inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--primary)]/10 px-2.5 text-[10px] font-semibold text-[var(--primary)] transition hover:bg-[var(--primary)]/15 disabled:opacity-50"
              >
                {openingInReader ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <BookOpenText size={12} />
                )}
                <span className="hidden sm:inline">{t("Open in Reading")}</span>
              </button>
            )}

            {downloadUrl && (
              <a
                href={downloadUrl}
                download={filename}
                title={t("Download")}
                aria-label={t("Download")}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <Download size={14} strokeWidth={1.7} />
              </a>
            )}
            {downloadUrl && (
              <button
                type="button"
                onClick={handleCopy}
                title={t("Copy link")}
                aria-label={t("Copy link")}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                {copied ? (
                  <Check
                    size={14}
                    strokeWidth={1.7}
                    className="text-emerald-500"
                  />
                ) : (
                  <Copy size={14} strokeWidth={1.7} />
                )}
              </button>
            )}
            <button
              ref={closeBtnRef}
              type="button"
              onClick={onClose}
              title={t("Close")}
              aria-label={t("Close")}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <X size={15} strokeWidth={1.8} />
            </button>
          </div>

          {readerError && (
            <div className="border-b border-[var(--destructive)]/20 bg-[var(--destructive)]/[0.06] px-4 py-2 text-[10.5px] text-[var(--destructive)]">
              {readerError}
            </div>
          )}

          {/* Body — mounted only after the slide-in animation is done so its
              (potentially expensive) markdown / syntax-highlight render can't
              steal main-thread frames from the chat squeeze. */}
          <div className="relative flex-1 overflow-hidden">
            {bodyMounted && (
              <PreviewBody
                source={renderedSource}
                previewUrl={previewUrl}
                kind={previewKind}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}

// Memoised so the close-time re-render of the outer drawer does NOT reconcile
// the heavy markdown / syntax-highlight tree underneath (which can take
// 10–50 ms with math + code blocks and was the visible "stutter" before the
// slide-out started). With stable source/previewUrl/kind props, memo bails
// the entire body subtree.
const PreviewBody = memo(function PreviewBody({
  source,
  previewUrl,
  kind,
}: {
  source: FilePreviewSource;
  previewUrl: string | null;
  kind: ReturnType<typeof previewKindFor> | null;
}) {
  const filename = source.filename;
  const rawExtractedTextUrl = source.extractedTextUrl;
  let extractedTextUrl: string | null = null;
  if (rawExtractedTextUrl) {
    extractedTextUrl =
      rawExtractedTextUrl.startsWith("http") ||
      rawExtractedTextUrl.startsWith("blob:")
        ? rawExtractedTextUrl
        : apiUrl(rawExtractedTextUrl);
  }

  // Office docs lean on extracted_text and degrade gracefully via the
  // OfficeTextPreview, even when previewUrl is missing (legacy messages).
  if (kind === "office-text") {
    return (
      <OfficeTextPreview
        filename={filename}
        extractedText={source.extractedText}
        extractedTextUrl={extractedTextUrl}
        url={previewUrl}
      />
    );
  }

  // Everything else needs a fetchable URL. Without one we fall back.
  if (!previewUrl) {
    return <FallbackPreview filename={filename} url={null} reason="legacy" />;
  }

  switch (kind) {
    case "pdf":
      return <PdfPreview url={previewUrl} filename={filename} />;
    case "docx":
      return <DocxPreview url={previewUrl} />;
    case "xlsx":
      return <XlsxPreview url={previewUrl} />;
    case "image":
      return <ImagePreview url={previewUrl} filename={filename} />;
    case "video":
      return <VideoPreview url={previewUrl} filename={filename} />;
    case "svg":
      return <SvgPreview url={previewUrl} filename={filename} />;
    case "markdown":
      return (
        <div className="h-full overflow-y-auto">
          <MarkdownPreview url={previewUrl} />
        </div>
      );
    case "code":
    case "text":
      return (
        <div className="h-full overflow-y-auto">
          <TextPreview url={previewUrl} filename={filename} />
        </div>
      );
    case "fallback":
    default:
      return <FallbackPreview filename={filename} url={previewUrl} />;
  }
});

PreviewBody.displayName = "PreviewBody";
