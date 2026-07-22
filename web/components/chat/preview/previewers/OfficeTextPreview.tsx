"use client";

import { Info, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import FallbackPreview from "./FallbackPreview";
import { useTextSource } from "./useTextSource";

/**
 * DOCX / XLSX / PPTX preview using the backend-extracted plain text. Browsers
 * cannot natively render OOXML and we choose not to ship mammoth.js / sheetjs
 * to keep the bundle slim. Showing the extracted text doubles as "see what
 * the LLM read", which is itself useful in a study tool.
 */
export default function OfficeTextPreview({
  filename,
  extractedText,
  extractedTextUrl,
  url,
}: {
  filename: string;
  extractedText: string | undefined;
  extractedTextUrl?: string | null;
  url: string | null;
}) {
  const { t } = useTranslation();
  const state = useTextSource(
    extractedText ? null : extractedTextUrl || null,
    extractedText,
  );

  if (!extractedText && !extractedTextUrl) {
    return <FallbackPreview filename={filename} url={url} />;
  }

  if (state.kind === "loading") {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-[12px] text-[var(--muted-foreground)]">
        <Loader2 size={14} className="animate-spin" />
        <span>{t("Loading preview…")}</span>
      </div>
    );
  }

  if (state.kind === "error") {
    return <FallbackPreview filename={filename} url={url} />;
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start gap-2 border-b border-[var(--border)] bg-[var(--muted)]/40 px-5 py-2.5 text-[11px] text-[var(--muted-foreground)]">
        <Info size={13} strokeWidth={1.6} className="mt-px shrink-0" />
        <p>
          {t(
            "Showing extracted text — the same content the assistant reads. Download the original to see full formatting.",
          )}
        </p>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <pre className="whitespace-pre-wrap break-words font-sans text-[13px] leading-relaxed text-[var(--foreground)]">
          {state.text}
        </pre>
      </div>
    </div>
  );
}
