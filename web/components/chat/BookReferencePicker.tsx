"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  Check,
  ChevronRight,
  Layers3,
  Loader2,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import PickerShell from "@/components/common/PickerShell";
import PickerHeader from "@/components/common/PickerHeader";
import { bookApi } from "@/lib/book-api";
import type { Book, BookDetail, Chapter, Page } from "@/lib/book-types";
import type {
  SelectedBookPage,
  SelectedBookReference,
} from "@/lib/book-references";

interface BookReferencePickerProps {
  open: boolean;
  initialReferences: SelectedBookReference[];
  onClose: () => void;
  onApply: (references: SelectedBookReference[]) => void;
}

function pageKey(bookId: string, pageId: string): string {
  return `${bookId}:${pageId}`;
}

function groupPages(detail: BookDetail | null): Array<{
  chapter: Chapter | null;
  pages: Page[];
}> {
  if (!detail) return [];
  const byId = new Map(detail.pages.map((page) => [page.id, page]));
  const used = new Set<string>();
  const groups: Array<{ chapter: Chapter | null; pages: Page[] }> = (
    detail.spine?.chapters || []
  ).map((chapter) => {
    const pages = chapter.page_ids
      .map((pageId) => byId.get(pageId))
      .filter((page): page is Page => Boolean(page));
    pages.forEach((page) => used.add(page.id));
    return { chapter, pages };
  });
  const orphanPages = detail.pages.filter((page) => !used.has(page.id));
  if (orphanPages.length) groups.push({ chapter: null, pages: orphanPages });
  return groups.filter((group) => group.pages.length > 0);
}

export default function BookReferencePicker({
  open,
  initialReferences,
  onClose,
  onApply,
}: BookReferencePickerProps) {
  const { t } = useTranslation();
  const [books, setBooks] = useState<Book[]>([]);
  const [details, setDetails] = useState<Record<string, BookDetail>>({});
  const [activeBookId, setActiveBookId] = useState<string | null>(null);
  const [selected, setSelected] = useState<SelectedBookReference[]>([]);
  const [query, setQuery] = useState("");
  const [loadingBooks, setLoadingBooks] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    if (!open) return;
    let mounted = true;
    // Re-seed selection each time the picker opens.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelected(initialReferences);
    setLoadingBooks(true);
    void bookApi
      .list()
      .then((data) => {
        if (!mounted) return;
        setBooks(data.books || []);
        setActiveBookId((current) => current || data.books?.[0]?.id || null);
      })
      .catch(() => {
        if (mounted) setBooks([]);
      })
      .finally(() => {
        if (mounted) setLoadingBooks(false);
      });
    return () => {
      mounted = false;
    };
  }, [initialReferences, open]);

  useEffect(() => {
    if (!open || !activeBookId || details[activeBookId]) return;
    let mounted = true;
    // Show detail loading before the async book lookup resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoadingDetail(true);
    void bookApi
      .get(activeBookId)
      .then((detail) => {
        if (!mounted) return;
        setDetails((prev) => ({ ...prev, [activeBookId]: detail }));
      })
      .catch(() => undefined)
      .finally(() => {
        if (mounted) setLoadingDetail(false);
      });
    return () => {
      mounted = false;
    };
  }, [activeBookId, details, open]);

  const filteredBooks = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return books;
    return books.filter((book) =>
      `${book.title} ${book.description}`.toLowerCase().includes(keyword),
    );
  }, [books, query]);

  const activeBook = books.find((book) => book.id === activeBookId) || null;
  const activeDetail = activeBookId ? details[activeBookId] || null : null;
  const pageGroups = useMemo(() => groupPages(activeDetail), [activeDetail]);
  const selectedKeys = useMemo(() => {
    const keys = new Set<string>();
    selected.forEach((book) =>
      book.pages.forEach((page) => keys.add(pageKey(book.bookId, page.pageId))),
    );
    return keys;
  }, [selected]);

  const togglePage = (book: Book, page: Page, chapter: Chapter | null) => {
    const nextPage: SelectedBookPage = {
      bookId: book.id,
      bookTitle: book.title || t("Untitled book"),
      pageId: page.id,
      pageTitle: page.title || t("Untitled chapter"),
      chapterId: chapter?.id || page.chapter_id,
      chapterTitle: chapter?.title || page.title || t("Untitled chapter"),
    };
    setSelected((prev) => {
      const existing = prev.find((ref) => ref.bookId === book.id);
      const selectedAlready = existing?.pages.some((p) => p.pageId === page.id);
      if (selectedAlready) {
        return prev
          .map((ref) =>
            ref.bookId === book.id
              ? { ...ref, pages: ref.pages.filter((p) => p.pageId !== page.id) }
              : ref,
          )
          .filter((ref) => ref.pages.length > 0);
      }
      if (existing) {
        return prev.map((ref) =>
          ref.bookId === book.id
            ? { ...ref, pages: [...ref.pages, nextPage] }
            : ref,
        );
      }
      return [
        ...prev,
        {
          bookId: book.id,
          bookTitle: book.title || t("Untitled book"),
          pages: [nextPage],
        },
      ];
    });
  };

  const toggleChapter = (
    book: Book,
    chapter: Chapter | null,
    pages: Page[],
  ) => {
    const allSelected = pages.every((page) =>
      selectedKeys.has(pageKey(book.id, page.id)),
    );
    setSelected((prev) => {
      const existing = prev.find((ref) => ref.bookId === book.id);
      const existingPages = existing?.pages || [];
      const pageIds = new Set(pages.map((page) => page.id));
      const remaining = allSelected
        ? existingPages.filter((page) => !pageIds.has(page.pageId))
        : [
            ...existingPages,
            ...pages
              .filter(
                (page) => !existingPages.some((p) => p.pageId === page.id),
              )
              .map((page) => ({
                bookId: book.id,
                bookTitle: book.title || t("Untitled book"),
                pageId: page.id,
                pageTitle: page.title || t("Untitled chapter"),
                chapterId: chapter?.id || page.chapter_id,
                chapterTitle:
                  chapter?.title || page.title || t("Untitled chapter"),
              })),
          ];
      const nextRef = {
        bookId: book.id,
        bookTitle: book.title || t("Untitled book"),
        pages: remaining,
      };
      const others = prev.filter((ref) => ref.bookId !== book.id);
      return nextRef.pages.length ? [...others, nextRef] : others;
    });
  };

  const selectedCount = selected.reduce(
    (total, ref) => total + ref.pages.length,
    0,
  );

  return (
    <PickerShell
      open={open}
      onClose={onClose}
      labelledBy="book-picker-title"
      className="p-4 backdrop-blur-md"
      backdropClass="bg-[var(--background)]/65"
    >
      <div className="surface-card flex h-[78vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] text-[var(--card-foreground)] shadow-[0_22px_70px_rgba(0,0,0,0.18)]">
        <PickerHeader
          icon={BookOpen}
          titleId="book-picker-title"
          title={t("Select Book Chapters")}
          subtitle={t(
            "Choose generated book chapters to ground the next answer.",
          )}
          onClose={onClose}
        />

        <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)]">
          <aside className="flex min-h-0 flex-col border-r border-[var(--border)] bg-[var(--background)]/40 p-4">
            <div className="relative mb-3">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("Search books")}
                className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] py-2.5 pl-9 pr-3 text-[13px] outline-none transition focus:border-[var(--primary)]/50 focus:ring-2 focus:ring-[var(--primary)]/15"
              />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)]">
              {loadingBooks ? (
                <div className="flex h-full min-h-[220px] items-center justify-center">
                  <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
                </div>
              ) : filteredBooks.length ? (
                <div className="divide-y divide-[var(--border)]">
                  {filteredBooks.map((book) => {
                    const active = book.id === activeBookId;
                    const selectedPages =
                      selected.find((ref) => ref.bookId === book.id)?.pages
                        .length || 0;
                    return (
                      <button
                        key={book.id}
                        onClick={() => setActiveBookId(book.id)}
                        className={`flex w-full items-center gap-3 px-3 py-3 text-left transition-colors ${
                          active
                            ? "bg-[var(--primary)]/8"
                            : "hover:bg-[var(--muted)]/40"
                        }`}
                      >
                        <BookOpen className="h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium text-[var(--foreground)]">
                            {book.title || t("Untitled book")}
                          </span>
                          <span className="mt-0.5 block text-[11px] text-[var(--muted-foreground)]">
                            {book.page_count || 0} {t("chapters")}
                          </span>
                        </span>
                        {selectedPages > 0 && (
                          <span className="rounded-full bg-[var(--primary)]/10 px-1.5 py-px text-[9px] font-semibold text-[var(--primary)]">
                            {selectedPages}
                          </span>
                        )}
                        <ChevronRight className="h-4 w-4 text-[var(--muted-foreground)]" />
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="px-5 py-12 text-center text-[13px] text-[var(--muted-foreground)]">
                  {t("No books found.")}
                </div>
              )}
            </div>
          </aside>

          <section className="min-h-0 overflow-y-auto p-5">
            {!activeBook ? (
              <div className="flex h-full items-center justify-center text-sm text-[var(--muted-foreground)]">
                {t("Select a book to view chapters.")}
              </div>
            ) : loadingDetail && !activeDetail ? (
              <div className="flex h-full items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
              </div>
            ) : (
              <div className="space-y-4">
                <div>
                  <h3 className="text-base font-semibold text-[var(--foreground)]">
                    {activeBook.title || t("Untitled book")}
                  </h3>
                  {activeBook.description && (
                    <p className="mt-1 line-clamp-2 text-sm text-[var(--muted-foreground)]">
                      {activeBook.description}
                    </p>
                  )}
                </div>
                {pageGroups.map(({ chapter, pages }) => {
                  const allSelected = pages.every((page) =>
                    selectedKeys.has(pageKey(activeBook.id, page.id)),
                  );
                  const showPageRows = pages.length > 1;
                  const firstPage = pages[0];
                  return (
                    <div
                      key={chapter?.id || pages[0]?.id}
                      className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--background)]/35"
                    >
                      <button
                        onClick={() =>
                          toggleChapter(activeBook, chapter, pages)
                        }
                        className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-[var(--muted)]/35 ${
                          showPageRows ? "border-b border-[var(--border)]" : ""
                        }`}
                      >
                        <span
                          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors ${
                            allSelected
                              ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                              : "border-[var(--border)] text-transparent"
                          }`}
                        >
                          <Check size={12} />
                        </span>
                        <Layers3 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium text-[var(--foreground)]">
                            {chapter?.title ||
                              firstPage?.title ||
                              t("Unassigned pages")}
                          </span>
                          <span className="text-[11px] text-[var(--muted-foreground)]">
                            {pages.length} {t("pages")}
                          </span>
                          {!showPageRows &&
                          firstPage?.learning_objectives?.length ? (
                            <span className="mt-1 line-clamp-2 text-[12px] leading-5 text-[var(--muted-foreground)]">
                              {firstPage.learning_objectives.join("; ")}
                            </span>
                          ) : null}
                        </span>
                      </button>
                      {showPageRows && (
                        <div className="divide-y divide-[var(--border)]">
                          {pages.map((page) => {
                            const checked = selectedKeys.has(
                              pageKey(activeBook.id, page.id),
                            );
                            return (
                              <button
                                key={page.id}
                                onClick={() =>
                                  togglePage(activeBook, page, chapter)
                                }
                                className={`flex w-full items-start gap-3 px-5 py-3 text-left transition-colors ${
                                  checked
                                    ? "bg-[var(--primary)]/8"
                                    : "hover:bg-[var(--muted)]/30"
                                }`}
                              >
                                <span
                                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors ${
                                    checked
                                      ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                                      : "border-[var(--border)] text-transparent"
                                  }`}
                                >
                                  <Check size={12} />
                                </span>
                                <span className="min-w-0 flex-1">
                                  <span className="block text-[13px] font-medium text-[var(--foreground)]">
                                    {page.title || t("Untitled chapter")}
                                  </span>
                                  {page.learning_objectives?.length ? (
                                    <span className="mt-1 line-clamp-2 text-[12px] leading-5 text-[var(--muted-foreground)]">
                                      {page.learning_objectives.join("; ")}
                                    </span>
                                  ) : null}
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-[var(--border)] px-5 py-4">
          <div className="text-sm text-[var(--muted-foreground)]">
            {selectedCount
              ? t("{{count}} chapters selected", { count: selectedCount })
              : t("No chapters selected")}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSelected([])}
              className="rounded-xl border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              {t("Clear")}
            </button>
            <button
              onClick={() => {
                onApply(selected);
                onClose();
              }}
              className="rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
            >
              {t("Apply")}
            </button>
          </div>
        </div>
      </div>
    </PickerShell>
  );
}
