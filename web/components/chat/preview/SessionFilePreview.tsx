"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeft, FileQuestion } from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiFetch } from "@/lib/api";
import { isRelativeFileReference, sessionFileUrl, useWindowsDesktop } from "../SessionFileLink";

/** Media, Office and text previews all recover to the same open conversation. */
export function SessionFilePreview({
  url, hasExtractedText, onBack, children
}: {
  url: string | null;
  hasExtractedText: boolean;
  onBack: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const [missing, setMissing] = useState<string | null>(null);
  const desktop = useWindowsDesktop();
  const relative = desktop && !!url && isRelativeFileReference(url);
  const published = desktop ? sessionFileUrl(url) : null;
  const source = published ?? (relative ? url : null);
  useEffect(() => {
    if (!source) return;
    const controller = new AbortController();
    void apiFetch(source, { method: "HEAD", cache: "no-store", signal: controller.signal })
      .then((response) => {
        // A stale relative file can match the frontend's dynamic chat page and return HTML with HTTP 200.
        const chatPage = relative && !/\.html?(?:[?#]|$)/i.test(source)
          && response.headers.get("content-type")?.startsWith("text/html");
        if (!controller.signal.aborted && (response.status === 404 || response.status === 410 || chatPage)) {
          setMissing(source);
        }
      })
      .catch(() => { /* The previewer handles network and format errors. */ });
    return () => controller.abort();
  }, [relative, source]);
  const missingSource = !url && !hasExtractedText && desktop;
  if (!missingSource && (!source || missing !== source)) return children;
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <FileQuestion aria-hidden="true" size={24} className="text-[var(--muted-foreground)]" />
      <p role="status" className="text-sm font-medium">{t("File unavailable")}</p>
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-2 rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]"
      >
        <ArrowLeft aria-hidden="true" size={15} />
        {t("Back to conversation")}
      </button>
    </div>
  );
}
