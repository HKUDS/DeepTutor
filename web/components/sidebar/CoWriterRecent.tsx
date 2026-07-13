"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  listCoWriterDocuments,
  type CoWriterDocumentSummary,
} from "@/lib/co-writer-api";
import { subscribeCoWriterChanges } from "@/lib/co-writer-events";
import { formatRelativeTime } from "@/lib/relative-time";

interface CoWriterRecentProps {
  collapsed?: boolean;
  limit?: number;
}

export function CoWriterRecent({
  collapsed = false,
  limit = 4,
}: CoWriterRecentProps) {
  const { i18n } = useTranslation();
  const [docs, setDocs] = useState<CoWriterDocumentSummary[]>([]);
  const pathname = usePathname();

  useEffect(() => {
    let active = true;
    void listCoWriterDocuments()
      .then((items) => {
        if (active) setDocs(items.slice(0, limit));
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [limit, pathname]);

  useEffect(() => {
    let active = true;
    const unsubscribe = subscribeCoWriterChanges(() => {
      void listCoWriterDocuments()
        .then((items) => {
          if (active) setDocs(items.slice(0, limit));
        })
        .catch(() => {});
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [limit]);

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
            {formatRelativeTime(Number(doc.updated_at) || 0, i18n.language)}
          </span>
        </Link>
      ))}
    </div>
  );
}
