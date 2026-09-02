"use client";

import { Download, ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { apiUrl } from "@/lib/api";
import type { Block } from "@/lib/book-types";

export interface AnimationBlockProps {
  block: Block;
}

interface Artifact {
  type?: string;
  url?: string;
  filename?: string;
  content_type?: string;
  label?: string;
}

function resolveAssetUrl(url: string): string {
  if (!url) return url;
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  return apiUrl(url);
}

export default function AnimationBlock({ block }: AnimationBlockProps) {
  const { t } = useTranslation();
  const payload = (block.payload || {}) as Record<string, unknown>;
  const rawVideoUrl = String(payload.video_url || "");
  const summary = String(payload.summary || "");
  const description = String(payload.description || "");
  const artifacts = (payload.artifacts as Artifact[] | undefined) || [];

  if (!rawVideoUrl && artifacts.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 p-4 text-xs italic text-[var(--muted-foreground)]">
        {t("(Animation payload is empty)")}
      </div>
    );
  }

  const primaryRaw = rawVideoUrl || artifacts[0]?.url || "";
  const primary = resolveAssetUrl(primaryRaw);
  const isVideo =
    primaryRaw.endsWith(".mp4") ||
    primaryRaw.endsWith(".webm") ||
    artifacts.some((a) => (a.content_type || "").startsWith("video/"));
  const filename =
    String(payload.filename || "") || artifacts[0]?.filename || "";

  return (
    <figure className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-3 shadow-sm">
      <div className="relative overflow-hidden rounded-xl bg-black">
        {isVideo ? (
          <video
            src={primary}
            controls
            playsInline
            preload="metadata"
            className="aspect-video h-auto w-full object-contain"
          />
        ) : (
          <img
            src={primary}
            alt={description || t("Animation frame")}
            className="h-auto w-full"
          />
        )}
        {primary && (
          <div className="absolute right-2 top-2 z-10 flex items-center gap-1">
            <a
              href={primary}
              target="_blank"
              rel="noopener noreferrer"
              title={t("Open in new tab")}
              className="inline-flex items-center gap-1 rounded-md bg-black/40 px-2 py-1 text-[10px] font-medium text-white/90 backdrop-blur-sm transition-colors hover:bg-black/60 hover:text-white"
            >
              <ExternalLink size={11} strokeWidth={1.8} />
              {t("Open")}
            </a>
            {isVideo && (
              <a
                href={primary}
                download={filename || true}
                title={t("Download video")}
                className="inline-flex items-center gap-1 rounded-md bg-black/40 px-2 py-1 text-[10px] font-medium text-white/90 backdrop-blur-sm transition-colors hover:bg-black/60 hover:text-white"
              >
                <Download size={11} strokeWidth={1.8} />
              </a>
            )}
          </div>
        )}
      </div>
      {(summary || description) && (
        <figcaption className="mt-3 text-xs leading-snug text-[var(--muted-foreground)]">
          <MarkdownRenderer
            content={summary || description}
            variant="default"
          />
        </figcaption>
      )}
    </figure>
  );
}
