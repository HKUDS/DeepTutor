"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  listCoWriterDocuments,
  type CoWriterDocumentSummary,
} from "@/lib/co-writer-api";
import { subscribeCoWriterChanges } from "@/lib/co-writer-events";

function relativeTime(seconds: number): string {
  if (!seconds || Number.isNaN(seconds)) return "";
  const diff = Date.now() / 1000 - seconds;
  if (diff < 60) return "now";
  const mins = Math.floor(diff / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  return `${days}d`;
}

interface CoWriterRecentProps {
  collapsed?: boolean;
  limit?: number;
}

export function CoWriterRecent({
  collapsed = false,
  limit = 4,
}: CoWriterRecentProps) {
  const [docs, setDocs] = useState<CoWriterDocumentSummary[]>([]);
  const pathname = usePathname();

  const refresh = useCallback(async () => {
    try {
      const items = await listCoWriterDocuments();
      setDocs(items.slice(0, limit));
    } catch {
      /* ignore */
    }
  }, [limit]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refresh();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh, pathname]);

  useEffect(() => {
    return subscribeCoWriterChanges(() => {
      void refresh();
    });
  }, [refresh]);

  if (docs.length === 0) return null;

  if (collapsed) return null;

  return (
    <div className="ml-5 border-l border-[var(--border)]/30 py-1">
      {docs.map((doc) => (
        <Link
          key={doc.id}
          href={`/co-writer/${encodeURIComponent(doc.id)}`}
          className="group flex items-center gap-2 rounded-r-lg py-1 pl-3 pr-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/40 hover:text-[var(--foreground)]"
        >
          <span className="block h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--muted-foreground)]/30" />
          <span className="min-w-0 flex-1 truncate text-[13px]">
            {doc.title || "Untitled draft"}
          </span>
          <span className="shrink-0 text-[10px] tabular-nums text-[var(--muted-foreground)]/40">
            {relativeTime(Number(doc.updated_at) || 0)}
          </span>
        </Link>
      ))}
    </div>
  );
}
