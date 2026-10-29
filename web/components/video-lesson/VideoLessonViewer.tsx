"use client";

import { Clapperboard, Code2, ExternalLink, Timer } from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiUrl } from "@/lib/api";
import type { VideoLessonResult } from "@/lib/video-lesson-types";

export default function VideoLessonViewer({
  result,
}: {
  result: VideoLessonResult;
}) {
  const { t } = useTranslation();
  const url = result.page.url;
  const src =
    url.startsWith("http://") || url.startsWith("https://")
      ? url
      : apiUrl(url);

  return (
    <div className="mb-3 space-y-3 rounded-2xl border border-[var(--border)] bg-[var(--card)]/70 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2 text-[12px] font-medium text-[var(--foreground)]">
          <Clapperboard size={14} className="shrink-0" />
          <span className="truncate">{result.title || t("Video Lesson")}</span>
        </div>
        <a
          href={src}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <ExternalLink size={12} />
          {t("Open in new tab")}
        </a>
      </div>

      {/* The page runs model-written code: scripts yes, same-origin access no. */}
      <iframe
        src={src}
        title={result.title || t("Video Lesson")}
        sandbox="allow-scripts"
        allow="fullscreen"
        allowFullScreen
        loading="lazy"
        className="aspect-video w-full rounded-xl border border-[var(--border)] bg-[#fdfcf9]"
      />

      {result.durationSeconds || result.attempts > 1 ? (
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
          {result.durationSeconds ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] px-2 py-0.5">
              <Timer size={12} />
              {t("{{seconds}} s", { seconds: result.durationSeconds })}
            </span>
          ) : null}
          {result.attempts > 1 ? (
            <span className="rounded-full border border-[var(--border)] px-2 py-0.5">
              {t("Fixed after {{count}} checks", { count: result.attempts })}
            </span>
          ) : null}
        </div>
      ) : null}

      {result.code ? (
        <details className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)]">
          <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-[12px] font-medium text-[var(--foreground)]">
            <Code2 size={14} />
            {t("View Remotion Code")}
          </summary>
          <pre className="max-h-[360px] overflow-auto border-t border-[var(--border)] px-3 py-3 font-mono text-[11px] leading-[1.6] text-[var(--foreground)]">
            {result.code}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
