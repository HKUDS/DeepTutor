"use client";

import { useTranslation } from "react-i18next";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { apiUrl } from "@/lib/api";
import ImagePreview from "@/components/chat/preview/previewers/ImagePreview";
import { useBinarySource } from "@/components/chat/preview/previewers/useBinarySource";

type Page = { title: string; preview_url: string };

function presentedPages(events: StreamEvent[]): Page[] {
  const pages = new Map<string, Page>();
  for (const event of events) {
    if (event.type !== "sources" || !["chat", "mastery_path"].includes(event.source)) continue;
    const sources = event.metadata.sources;
    if (!Array.isArray(sources)) continue;
    for (const source of sources) {
      if (!source || typeof source !== "object") continue;
      if (source.presentation !== "teaching" && source.presentation !== "reveal") continue;
      const { title, preview_url } = source;
      // Authenticated requests must stay on the exact native source-page route.
      if (typeof title !== "string" || typeof preview_url !== "string" ||
          !/^\/api\/knowledge-bases\/[A-Za-z0-9_%.-]+\/source-page\?/.test(preview_url)) continue;
      const parsed = new URL(preview_url, "https://source.invalid");
      if (parsed.pathname !== preview_url.split("?")[0]) continue;
      pages.set(preview_url, { title, preview_url });
    }
  }
  return [...pages.values()].slice(0, 12);
}

function SourcePage({ page }: { page: Page }) {
  const { t } = useTranslation();
  const state = useBinarySource(apiUrl(page.preview_url), "image/png");
  const url = state.kind === "ready" ? state.objectUrl : null;
  return <figure className="my-3 rounded-lg border border-[var(--border)] p-2">
    <figcaption className="mb-2 break-words text-xs text-[var(--muted-foreground)]">{page.title}</figcaption>
    {url ? <div className="h-96 w-full"><ImagePreview url={url} filename={page.title} /></div>
      : <p role="status" className="text-sm">{state.kind === "error" ? t("Failed to load image.") : t("Loading...")}</p>}
  </figure>;
}

/** Render publication receipts; publication does not prove that a learner viewed a page. */
export function MasterySourcePresentation({ events }: { events: StreamEvent[] }) {
  return <>{presentedPages(events).map(page => <SourcePage key={page.preview_url} page={page} />)}</>;
}
