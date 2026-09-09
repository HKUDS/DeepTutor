"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Compass,
  Download,
  Loader2,
  RotateCcw,
} from "lucide-react";
import { bookApi } from "@/lib/book-api";
import { useTranslation } from "react-i18next";
import { ActivityMark } from "@/components/activity";
import type { ActivityState, MarkTone } from "@/components/activity";
import type { Book, Page, Spine } from "@/lib/book-types";

const STATUS_LABEL: Record<string, string> = {
  pending: "Queued",
  planning: "Planning",
  generating: "Compiling",
  ready: "Ready",
  partial: "Partial",
  error: "Failed",
};

/**
 * A chapter's status as the product's activity vocabulary.
 *
 * The list used to end every row with an uppercase tracked pill spelling the
 * status out — six characters of shouting per row, in a column 232px wide,
 * repeated down the whole chapter list. The mark says the same thing in 12px
 * and animates while the chapter is actually being written, which is the one
 * state a reader watches for.
 *
 * `tone` is what separates the two resting states, which the four-state
 * vocabulary alone cannot: a written chapter and a queued one are both "not
 * running", and a reader scanning the list wants to know which is which at a
 * glance. Written gets a solid blue dot, queued a hollow grey ring.
 */
const PAGE_MARK: Record<string, { state: ActivityState; tone: MarkTone }> = {
  pending: { state: "done", tone: "muted" },
  planning: { state: "running", tone: "muted" },
  generating: { state: "running", tone: "muted" },
  ready: { state: "done", tone: "accent" },
  partial: { state: "error", tone: "muted" },
  error: { state: "error", tone: "muted" },
};

const RESTING_MARK = { state: "done", tone: "muted" } as const;

/** Sentinel key for the 导览 group (overview pages, pages outside the spine). */
const GUIDE_KEY = "__guide__";

interface SectionGroup {
  key: string;
  title: string;
  pageIds: string[];
}

interface ChapterGroup {
  key: string;
  title: string;
  sections: SectionGroup[];
  /** Pages of this chapter that no 节 claimed (章直挂). */
  pageIds: string[];
}

/**
 * P6 sidebar grouping. Pages aggregate under their spine chapter (P6-a);
 * when the spine carries 节级 children (P6-b) each chapter renders its
 * sections between the chapter and its pages. Overview pages and pages no
 * spine chapter claims fall into the 导览 group, which sorts first.
 */
function buildGroups(pages: Page[], spine: Spine | null | undefined): ChapterGroup[] {
  const chapters = spine?.chapters ?? [];
  const pageById = new Map(pages.map((p) => [p.id, p]));
  const chapterById = new Map(chapters.map((c) => [c.id, c]));
  const groups = new Map<string, ChapterGroup>();
  const guide: ChapterGroup = { key: GUIDE_KEY, title: "", sections: [], pageIds: [] };
  for (const chapter of chapters) {
    groups.set(chapter.id, { key: chapter.id, title: chapter.title, sections: [], pageIds: [] });
  }

  for (const page of pages) {
    const isGuide = page.content_type === "overview" || !chapterById.has(page.chapter_id);
    (isGuide ? guide : groups.get(page.chapter_id)!).pageIds.push(page.id);
  }

  // P6-b: 节层 claims its pages out of the chapter's direct list.
  const inSection = new Set<string>();
  for (const chapter of chapters) {
    const group = groups.get(chapter.id);
    if (!group) continue;
    for (const child of chapter.children ?? []) {
      const pageIds = (child.page_ids ?? []).filter((id) => pageById.has(id));
      if (pageIds.length === 0) continue;
      pageIds.forEach((id) => inSection.add(id));
      group.sections.push({ key: `${chapter.id}:${child.title}`, title: child.title, pageIds });
    }
    group.pageIds = group.pageIds.filter((id) => !inSection.has(id));
  }

  const ordered = [guide, ...groups.values()].filter(
    (g) => g.pageIds.length > 0 || g.sections.length > 0,
  );
  // A generated book has one page per chapter — grouping would just repeat
  // every chapter title above its own page. Only textbook-style books
  // (multi-page chapters or 节层) get the grouped tree.
  const multiPage = ordered.some((g) => g.sections.length > 0 || g.pageIds.length > 1);
  return multiPage ? ordered : [];
}

export interface BookSidebarProps {
  book: Book | null;
  onBackToLibrary: () => void;
  pages?: Page[];
  /** P6: chapter/节 grouping source; absent or page-per-chapter → flat list. */
  spine?: Spine | null;
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
  spine = null,
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
  // Collapsed group keys; everything starts expanded so a fresh open shows
  // the whole reading structure at once.
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const groups = useMemo(() => buildGroups(pages, spine), [pages, spine]);
  const grouped = groups.length > 0;
  const pageById = useMemo(() => new Map(pages.map((p) => [p.id, p])), [pages]);

  // Destructive controls forget: an armed state that outlives the interaction
  // turns the next stray click into an unconfirmed rebuild.
  useEffect(() => {
    if (!confirmRebuild) return;
    const timer = setTimeout(() => setConfirmRebuild(false), 3500);
    return () => clearTimeout(timer);
  }, [confirmRebuild]);

  const toggleGroup = (key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

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
                title={page.display_title || page.title || t("Untitled")}
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

  const renderPageRow = (page: Page, indentClass: string) => {
    const active = page.id === selectedPageId;
    const isOverview = page.content_type === "overview";
    return (
      <button
        onClick={() => onSelectPage?.(page.id)}
        className={`flex w-full items-start justify-between gap-2 rounded-md py-1.5 pr-2 text-left text-xs ${indentClass} ${
          active
            ? "bg-[var(--primary)]/15 text-[var(--foreground)]"
            : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
        } ${isOverview ? "border border-dashed border-[var(--border)]" : ""}`}
      >
        <span className="flex min-w-0 items-start gap-1.5">
          {isOverview && (
            <Compass className="mt-[1px] h-3 w-3 shrink-0 text-[var(--primary)]" />
          )}
          <span className="line-clamp-2">{page.display_title || page.title || t("Untitled")}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {bookmarkedPageIds?.includes(page.id) && (
            <span
              className="h-1.5 w-1.5 rounded-full bg-[var(--primary)]"
              title={t("Bookmarked")}
            />
          )}
          {/* The status word survives as the tooltip:
              available when wanted, not shouted on every row.
              A chapter already read keeps the blue dot but
              dimmed — one mark, two facts. */}
          <span
            title={t(STATUS_LABEL[page.status] || page.status)}
            className={`inline-flex items-center ${
              page.status === "ready" && visitedPageIds?.includes(page.id) ? "opacity-45" : ""
            }`}
          >
            <ActivityMark {...(PAGE_MARK[page.status] || RESTING_MARK)} className="mt-[1px]" />
          </span>
        </span>
      </button>
    );
  };

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
        ) : grouped ? (
          <>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
              {t("Chapters")}
            </div>
            <div className="space-y-1">
              {groups.map((group) => {
                const isGuide = group.key === GUIDE_KEY;
                const collapsedGroup = collapsedGroups.has(group.key);
                const guideLabel = t("Guide");
                return (
                  <div key={group.key}>
                    <button
                      onClick={() => toggleGroup(group.key)}
                      className={`flex w-full items-center gap-1 rounded-md px-1 py-1 text-left text-[11px] font-semibold text-[var(--foreground)] ${
                        isGuide ? "text-[var(--muted-foreground)]" : ""
                      }`}
                    >
                      {collapsedGroup ? (
                        <ChevronRight className="h-3 w-3 shrink-0" />
                      ) : (
                        <ChevronDown className="h-3 w-3 shrink-0" />
                      )}
                      <span className="truncate" title={isGuide ? guideLabel : group.title}>
                        {isGuide ? guideLabel : group.title}
                      </span>
                    </button>
                    {!collapsedGroup && (
                      <div className="space-y-1">
                        {group.sections.map((section) => (
                          <div key={section.key}>
                            <div
                              className="truncate pl-5 pr-2 pt-1 text-[11px] font-medium text-[var(--muted-foreground)]"
                              title={section.title}
                            >
                              {section.title}
                            </div>
                            {section.pageIds.map((pageId) => {
                              const page = pageById.get(pageId);
                              return page ? renderPageRow(page, "pl-7") : null;
                            })}
                          </div>
                        ))}
                        {group.pageIds.map((pageId) => {
                          const page = pageById.get(pageId);
                          return page ? renderPageRow(page, page.parent_page_id ? "pl-5" : "pl-3") : null;
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
              {t("Chapters")}
            </div>
            <ul className="space-y-1">
              {pages.map((page) => (
                <li key={page.id}>{renderPageRow(page, page.parent_page_id ? "pl-5" : "pl-2")}</li>
              ))}
            </ul>
          </>
        )}
      </section>
    </aside>
  );
}
