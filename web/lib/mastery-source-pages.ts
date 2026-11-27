/**
 * Source pages a Mastery tutor chose to show, read off the wire.
 *
 * Both carriers, the `sources` stream event and the presenting tool's own
 * result, hold the same rows, so one validator decides what may be fetched.
 */

import type { StreamEvent } from "@/features/chat/model/protocol";
import { toolResultPayload } from "@/lib/tool-event";

export type PresentedPage = { title: string; preview_url: string };

/** Pages marked for explicit display; private inspection rows are dropped. */
export function presentedPagesFromSources(sources: unknown): PresentedPage[] {
  if (!Array.isArray(sources)) return [];
  const pages: PresentedPage[] = [];
  for (const source of sources) {
    if (!source || typeof source !== "object") continue;
    if (source.presentation !== "teaching" && source.presentation !== "reveal") continue;
    const { title, preview_url } = source;
    // Authenticated requests must stay on the exact native source-page route.
    if (typeof title !== "string" || typeof preview_url !== "string" ||
        !/^\/api\/knowledge-bases\/[A-Za-z0-9_%.-]+\/source-page\?/.test(preview_url)) continue;
    const parsed = new URL(preview_url, "https://source.invalid");
    if (parsed.pathname !== preview_url.split("?")[0]) continue;
    pages.push({ title, preview_url });
  }
  return pages;
}

/** The pages a `rag` tool result presented at its own call, if it did. */
export function presentedPagesOfToolResult(event: StreamEvent): PresentedPage[] {
  if (event.type !== "tool_result") return [];
  return presentedPagesFromSources(toolResultPayload(event.metadata, "presented_sources"));
}
