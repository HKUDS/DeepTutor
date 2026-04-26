"use client";

import { ArrowLeft, Compass } from "lucide-react";
import type { Book, Page } from "@/lib/book-types";

const STATUS_LABEL: Record<string, string> = {
  pending: "Queued",
  planning: "Planning",
  generating: "Compiling",
  ready: "Ready",
  partial: "Partial",
  error: "Failed",
};

export interface BookSidebarProps {
  book: Book | null;
  onBackToLibrary: () => void;
  pages?: Page[];
  selectedPageId?: string | null;
  onSelectPage?: (id: string) => void;
}

export default function BookSidebar({
  book,
  onBackToLibrary,
  pages = [],
  selectedPageId = null,
  onSelectPage,
}: BookSidebarProps) {
  return (
    <aside className="flex max-h-[42dvh] w-full shrink-0 flex-col gap-3 border-b border-[var(--border)] bg-[var(--card)]/40 px-3 py-3 md:h-full md:max-h-none md:w-[232px] md:border-b-0 md:border-r md:py-4">
      <button
        onClick={onBackToLibrary}
        className="inline-flex items-center gap-1.5 self-start rounded-md px-2 py-1 text-xs font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> All books
      </button>

      {book && (
        <div className="px-1">
          <div
            className="line-clamp-2 text-sm font-semibold text-[var(--foreground)]"
            title={book.title || "Untitled book"}
          >
            {book.title || "Untitled book"}
          </div>
          <div className="mt-0.5 text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">
            {book.status} · {book.chapter_count || 0} chapters
          </div>
        </div>
      )}

      <section className="min-h-0 flex-1 overflow-y-auto md:overflow-y-auto">
        {pages.length === 0 ? (
          <div className="rounded-md border border-dashed border-[var(--border)] px-2 py-3 text-xs text-[var(--muted-foreground)]">
            Pages will appear here once the spine is confirmed.
          </div>
        ) : (
          <>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
              Chapters
            </div>
            <ul className="flex gap-1 overflow-x-auto pb-1 hide-scrollbar md:block md:space-y-1 md:overflow-x-visible md:pb-0">
              {pages.map((page) => {
                const active = page.id === selectedPageId;
                const isOverview = page.content_type === "overview";
                return (
                  <li key={page.id} className="min-w-[180px] md:min-w-0">
                    <button
                      onClick={() => onSelectPage?.(page.id)}
                      className={`flex w-full items-start justify-between gap-2 rounded-md px-2 py-1.5 text-left text-xs ${
                        active
                          ? "bg-[var(--primary)]/15 text-[var(--foreground)]"
                          : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
                      } ${
                        isOverview
                          ? "border border-dashed border-[var(--border)]"
                          : ""
                      }`}
                    >
                      <span className="flex min-w-0 items-start gap-1.5">
                        {isOverview && (
                          <Compass className="mt-[1px] h-3 w-3 shrink-0 text-[var(--primary)]" />
                        )}
                        <span className="line-clamp-2">
                          {page.title || "Untitled"}
                        </span>
                      </span>
                      <span className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-[var(--muted-foreground)]">
                        {STATUS_LABEL[page.status] || page.status}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </section>
    </aside>
  );
}
