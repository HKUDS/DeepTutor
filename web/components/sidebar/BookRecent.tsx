"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { bookApi } from "@/lib/book-api";
import type { Book } from "@/lib/book-types";
import { formatRelativeTime } from "@/lib/relative-time";

const STATUS_DOT: Record<string, string> = {
  ready: "bg-emerald-400",
  partial: "bg-amber-400",
  generating: "bg-sky-400",
  planning: "bg-sky-400",
  pending: "bg-[var(--muted-foreground)]/30",
  draft: "bg-[var(--muted-foreground)]/30",
  spine_ready: "bg-violet-400",
  error: "bg-rose-400",
};

interface BookRecentProps {
  collapsed?: boolean;
  limit?: number;
}

export function BookRecent({ collapsed = false, limit = 4 }: BookRecentProps) {
  const { i18n } = useTranslation();
  const [books, setBooks] = useState<Book[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { books: items } = await bookApi.list();
        // `list_books` already returns newest-first (engine sorts by
        // updated_at desc), so this is presentation only.
        if (!cancelled) setBooks(items.slice(0, limit));
      } catch {
        /* the sidebar is decoration; a failed fetch just shows nothing */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [limit]);

  if (books.length === 0) return null;

  if (collapsed) return null;

  return (
    <div className="ml-5 border-l border-[var(--border)]/30 py-1">
      {books.map((book) => {
        const dot =
          STATUS_DOT[book.status] || "bg-[var(--muted-foreground)]/30";
        return (
          <Link
            key={book.id}
            href={`/book?book=${encodeURIComponent(book.id)}`}
            className="group flex items-center gap-2 rounded-r-lg py-1 pl-3 pr-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/40 hover:text-[var(--foreground)]"
          >
            <span
              className={`block h-1.5 w-1.5 shrink-0 rounded-full ${dot}`}
            />
            <span className="min-w-0 flex-1 truncate text-[13px]">
              {book.title || "Untitled book"}
            </span>
            <span className="shrink-0 text-[10px] tabular-nums text-[var(--muted-foreground)]/40">
              {formatRelativeTime(Number(book.updated_at) || 0, i18n.language)}
            </span>
          </Link>
        );
      })}
    </div>
  );
}
