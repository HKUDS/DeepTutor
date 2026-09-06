"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { MessageAttachment } from "@/features/chat/ChatStateAdapter";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { apiUrl } from "@/lib/api";
import {
  collectRagSourceFigures,
  type RagSourceFigure,
} from "@/lib/rag-source-figures";

function attachmentForFigure(figure: RagSourceFigure): MessageAttachment {
  const pathName = figure.image_url.split("?")[0]?.split("/").pop() || "figure";
  const filename = decodeURIComponent(pathName);
  return {
    type: "image",
    filename,
    url: figure.image_url,
    mime_type: figure.mime_type || "image/png",
    title: figure.title || filename,
    caption: figure.image_description,
  };
}

export function RagSourceFigures({
  events,
  onOpen,
}: {
  events?: StreamEvent[];
  onOpen?: (attachment: MessageAttachment) => void;
}) {
  const { t } = useTranslation();
  const figures = useMemo(() => collectRagSourceFigures(events), [events]);
  if (!figures.length) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {figures.map((figure) => {
        const src = apiUrl(figure.image_url);
        const label =
          figure.title ||
          figure.image_description ||
          t("Retrieved figure");
        const attachment = attachmentForFigure(figure);
        return (
          <button
            key={figure.image_url}
            type="button"
            onClick={onOpen ? () => onOpen(attachment) : undefined}
            className="group max-w-[200px] overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)] text-left shadow-sm transition hover:border-[var(--foreground)]/30"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={src}
              alt={label}
              loading="lazy"
              className="block h-[120px] w-full bg-[var(--background)] object-contain"
            />
            <span className="block truncate px-2 py-1 text-[11px] text-[var(--muted-foreground)]">
              {label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
