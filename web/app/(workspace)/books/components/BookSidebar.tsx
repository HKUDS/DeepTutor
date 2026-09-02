"use client";

import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Compass,
  Download,
  Loader2,
  RotateCcw,
} from "lucide-react";
import { bookApi } from "@/lib/book-api";
import { useTranslation } from "react-i18next";
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
  onRebuild?: () => void;
  rebuilding?: boolean;
  visitedPageIds?: string[];
  bookmarkedPageIds?: string[];
}

export default function BookSidebar({
  book,
  onBackToLibrary,
  pages = [],
  selectedPageId = null,
  onSelectPage,
  onRebuild,
  rebuilding = false,
  visitedPageIds,
  bookmarkedPageIds,
}: BookSidebarProps) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);
  const [confirmRebuild, setConfirmRebuild] = useState(false);

  // Destructive controls forget: an armed state that outlives the interaction
  // turns the next stray click into an unconfirmed rebuild.
  useEffect(() => {
    if (!confirmRebuild) return;
    const timer = setTimeout(() => setConfirmRebuild(false), 3500);
    return () => clearTimeout(timer);
  }, [confirmRebuild]);

  if (collapsed) {
    return (
      <aside className="flex h-full w-14 flex-col items-center gap-3 border-r border-[var(--border)] bg-[var(--card)]/40 px-2 py-4">
        <button
          onClick={onBackToLibrary}
          title={t("All books")}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <button
          onClick={() => setCollapsed(false)}
          title={t("Expand chapters")}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
        <div className="mt-1 h-px w-8 bg-[var(--border)]" />
        <div className="flex flex-1 flex-col items-center gap-1 overflow-y-auto">
          {pages.map((page, index) => {
            const active = page.id === selectedPageId;
            return (
              <button
                key={page.id}
                onClick={() => onSelectPage?.(page.id)}
                title={page.title || t("Untitled")}
                className={`inline-flex h-8 w-8 items-center justify-center rounded-md text-[11px] font-semibold ${
                  active
                    ? "bg-[var(--primary)]/15 text-[var(--foreground)]"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
                }`}
              >
                {page.content_type === "overview" ? (
                  <Compass className="h-3.5 w-3.5" />
                ) : (
                  index + 1
                )}
              </button>
            );
          })}
        </div>
      </aside>
    );
  }

  return (
    <aside className="flex h-full w-[232px] flex-col gap-3 border-r border-[var(--border)] bg-[var(--card)]/40 px-3 py-4">
      <div className="flex items-center justify-between gap-2">
        <button
          onClick={onBackToLibrary}
          className="inline-flex items-center gap-1.5 self-start rounded-md px-2 py-1 text-xs font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> {t("All books")}
        </button>
        <button
          onClick={() => setCollapsed(true)}
          title={t("Collapse chapters")}
          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
      </div>

      {book && (
        <div className="px-1">
          <div
            className="line-clamp-2 text-sm font-semibold text-[var(--foreground)]"
            title={book.title || t("Untitled book")}
          >
            {book.title || t("Untitled book")}
          </div>
          <div className="mt-0.5 text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">
            {t(book.status)} ·{" "}
            {t("{{count}} chapters", { count: book.chapter_count || 0 })}
          </div>
        </div>
      )}

      {book && (
        <a
          href={bookApi.exportUrl(book.id)}
          download
          className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1.5 text-xs font-medium text-[var(--muted-foreground)] hover:border-[var(--primary)]/40 hover:text-[var(--primary)]"
        >
          <Download className="h-3.5 w-3.5" />
          {t("Export Markdown")}
        </a>
      )}

      {/* Rebuild deletes every page AND resets progress — reading position,
          bookmarks, quiz history, notes and in-place edits all go. It needs the
          same two-step confirmation the library uses for deleting a book. */}
      {onRebuild && (
        <div className="space-y-1">
          <button
            type="button"
            onClick={() => {
              if (confirmRebuild) {
                setConfirmRebuild(false);
                onRebuild();
              } else {
                setConfirmRebuild(true);
              }
            }}
            onBlur={() => setConfirmRebuild(false)}
            disabled={rebuilding}
            className={`inline-flex w-full items-center justify-center gap-1.5 rounded-md border px-2 py-1.5 text-xs font-medium disabled:opacity-60 ${
              confirmRebuild
                ? "border-rose-400/60 bg-rose-500/10 text-rose-600 dark:text-rose-300"
                : "border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:border-[var(--primary)]/40 hover:text-[var(--primary)]"
            }`}
          >
            {rebuilding ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RotateCcw className="h-3.5 w-3.5" />
            )}
            {rebuilding
              ? t("Rebuilding…")
              : confirmRebuild
                ? t("Click again to rebuild")
                : t("Rebuild book")}
          </button>
          {confirmRebuild && !rebuilding && (
            <p className="px-1 text-[10px] leading-snug text-[var(--muted-foreground)]">
              {t(
                "Replaces every generated chapter and clears your reading progress, bookmarks, notes and edits.",
              )}
            </p>
          )}
        </div>
      )}

      <section className="flex-1 overflow-y-auto">
        {pages.length === 0 ? (
          <div className="rounded-md border border-dashed border-[var(--border)] px-2 py-3 text-xs text-[var(--muted-foreground)]">
            {t("Pages will appear here once the spine is confirmed.")}
          </div>
        ) : (
          <>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
              {t("Chapters")}
            </div>
            <ul className="space-y-1">
              {pages.map((page) => {
                const active = page.id === selectedPageId;
                const isOverview = page.content_type === "overview";
                return (
                  <li key={page.id}>
                    <button
                      onClick={() => onSelectPage?.(page.id)}
                      className={`flex w-full items-start justify-between gap-2 rounded-md py-1.5 pr-2 text-left text-xs ${
                        page.parent_page_id ? "pl-5" : "pl-2"
                      } ${
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
                          {page.title || t("Untitled")}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-1">
                        {bookmarkedPageIds?.includes(page.id) && (
                          <span
                            className="h-1.5 w-1.5 rounded-full bg-[var(--primary)]"
                            title={t("Bookmarked")}
                          />
                        )}
                        {page.status === "ready" && (
                          <span
                            className={
                              visitedPageIds?.includes(page.id)
                                ? "text-[var(--muted-foreground)]/70"
                                : "text-[var(--primary)]"
                            }
                            title={
                              visitedPageIds?.includes(page.id)
                                ? t("Read")
                                : t("Unread")
                            }
                          >
                            {visitedPageIds?.includes(page.id) ? "✓" : "•"}
                          </span>
                        )}
                        <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-[var(--muted-foreground)]">
                          {t(STATUS_LABEL[page.status] || page.status)}
                        </span>
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
