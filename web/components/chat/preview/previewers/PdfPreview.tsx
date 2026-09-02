"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { FilePreviewSource } from "../previewerFor";

/**
 * PDF preview powered by the browser's built-in viewer (PDF.js in Chrome /
 * Firefox, Preview in Safari). Loads the original file from /files/attachments
 * via an <iframe> — zero extra bundle weight.
 *
 * The "load" event sometimes fires twice in WebKit because of the inline
 * UA toolbar; we only flip the loading flag on the first one.
 */
export default function PdfPreview({
  url,
  filename,
}: {
  url: string;
  filename: FilePreviewSource["filename"];
}) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(true);

  return (
    <div className="relative h-full w-full bg-[var(--muted)]/30">
      {loading && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
          <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 size={14} className="animate-spin" />
            <span>{t("Loading preview…")}</span>
          </div>
        </div>
      )}
      <iframe
        title={filename}
        src={url}
        className="h-full w-full border-0 bg-[var(--background)]"
        onLoad={() => setLoading(false)}
      />
    </div>
  );
}
