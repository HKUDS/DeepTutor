"use client";

import { useTranslation } from "react-i18next";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { apiUrl } from "@/lib/api";
import ImagePreview from "@/components/chat/preview/previewers/ImagePreview";
import { useBinarySource } from "@/components/chat/preview/previewers/useBinarySource";
import { presentedPagesFromSources, type PresentedPage } from "@/lib/mastery-source-pages";

type Page = PresentedPage;

function presentedPages(events: StreamEvent[], placed: ReadonlySet<string>): Page[] {
  const pages = new Map<string, Page>();
  for (const event of events) {
    if (event.type !== "sources" || !["chat", "mastery_path"].includes(event.source)) continue;
    for (const page of presentedPagesFromSources(event.metadata.sources)) {
      // A page already shown at its tool call is not stacked again below.
      if (!placed.has(page.preview_url)) pages.set(page.preview_url, page);
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
export function MasterySourcePresentation({ events, placed }: {
  events: StreamEvent[];
  /** Preview URLs already rendered where their tool call happened. */
  placed?: ReadonlySet<string>;
}) {
  return <>{presentedPages(events, placed ?? NONE).map(page => <SourcePage key={page.preview_url} page={page} />)}</>;
}

const NONE: ReadonlySet<string> = new Set();

/** The pages one tool call presented, shown where that call happened. */
export function MasterySourcePages({ pages }: { pages: PresentedPage[] }) {
  return <>{pages.map(page => <SourcePage key={page.preview_url} page={page} />)}</>;
}
