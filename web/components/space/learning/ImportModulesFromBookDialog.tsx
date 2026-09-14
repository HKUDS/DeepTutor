"use client";

import { useEffect, useState, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import { AlertCircle, BookOpen, Check, Loader2, X } from "lucide-react";

import { bookApi } from "@/lib/book-api";
import type { Book } from "@/lib/book-types";
import { importFromBook } from "@/lib/learning-api";

import { useModalDialog } from "@/hooks/useModalDialog";

/**
 * Fill an empty topic with modules from a textbook.
 *
 * Lists the bookshelf, then sends the chosen book's spine chapters to
 * ``POST /api/mastery-paths/progress/{path_id}/import-from-book`` — one chapter
 * per module. The endpoint requires every module to carry at least one
 * knowledge point, so a chapter without learning objectives falls back to its
 * own title.
 */
export function ImportModulesFromBookDialog({
  pathId,
  onClose,
  onImported,
  returnFocusRef,
}: {
  pathId: string;
  onClose: () => void;
  onImported: (moduleCount: number) => void;
  returnFocusRef: RefObject<HTMLElement | null>;
}) {
  const { t } = useTranslation();
  const [books, setBooks] = useState<Book[] | null>(null);
  const [selected, setSelected] = useState<Book | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useModalDialog(onClose, busy, returnFocusRef);

  useEffect(() => {
    let disposed = false;
    bookApi
      .list()
      .then(({ books: listed }) => {
        if (!disposed) setBooks(listed);
      })
      .catch((reason: unknown) => {
        if (!disposed)
          setError(
            reason instanceof Error ? reason.message : t("Loading failed."),
          );
      });
    return () => {
      disposed = true;
    };
  }, [t]);

  const importBook = async (book: Book) => {
    setBusy(true);
    setError(null);
    try {
      const { spine } = await bookApi.getSpine(book.id);
      const chapters = [...(spine?.chapters ?? [])].sort(
        (a, b) => a.order - b.order,
      );
      // Overview and deep-dive chapters are engine-injected auxiliaries, not
      // the textbook's teaching order — skip them when the spine has real ones.
      const authored = chapters.filter(
        (chapter) => !chapter.auto_overview && !chapter.deep_dive,
      );
      const usable = authored.length > 0 ? authored : chapters;
      if (usable.length === 0) {
        setError(t("This book has no chapters to import yet."));
        setBusy(false);
        return;
      }
      const result = await importFromBook(
        pathId,
        usable.map((chapter) => ({
          title: chapter.title,
          knowledge_points:
            chapter.learning_objectives.length > 0
              ? chapter.learning_objectives
              : [chapter.title],
        })),
      );
      onImported(
        typeof result?.module_count === "number"
          ? result.module_count
          : usable.length,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("Import failed."));
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[var(--overlay)] p-0 backdrop-blur-[2px] sm:items-center sm:p-6">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-from-book-title"
        aria-describedby="import-from-book-description"
        tabIndex={-1}
        className="flex max-h-[92dvh] w-full max-w-2xl flex-col overflow-hidden rounded-t-[26px] border border-[var(--border)] bg-[var(--card)] shadow-2xl outline-none sm:rounded-xl"
      >
        <header className="flex items-start justify-between border-b border-[var(--border)] px-5 py-4 sm:px-7">
          <div className="min-w-0">
            <h2
              id="import-from-book-title"
              className="text-xl font-semibold tracking-tight"
            >
              {t("Generate modules from a book")}
            </h2>
            <p
              id="import-from-book-description"
              className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]"
            >
              {t(
                "Pick a textbook — each chapter becomes a module, and its learning objectives become the knowledge points.",
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label={t("Close")}
            className="rounded-lg p-2 text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-7">
          {books === null && !error ? (
            <div className="flex items-center justify-center py-16 text-[var(--muted-foreground)]">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : books && books.length > 0 ? (
            <div className="grid gap-2 sm:grid-cols-2">
              {books.map((book) => {
                const active = selected?.id === book.id;
                const unavailable = book.status === "error";
                return (
                  <button
                    key={book.id}
                    type="button"
                    onClick={() => setSelected(book)}
                    aria-pressed={active}
                    disabled={busy || unavailable}
                    className={`flex min-h-16 items-center gap-3 rounded-xl border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-55 ${
                      active
                        ? "border-[var(--primary)] bg-[var(--primary)]/[0.06]"
                        : "border-[var(--border)] hover:bg-[var(--accent)]/60"
                    }`}
                  >
                    <span
                      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border ${
                        active
                          ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                          : "border-[var(--input)]"
                      }`}
                    >
                      {active && <Check className="h-3 w-3" />}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-[var(--foreground)]">
                        {book.title}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-[var(--muted-foreground)]">
                        {unavailable
                          ? t("Currently unavailable")
                          : t("{{count}} chapters", {
                              count: book.chapter_count,
                            })}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="flex items-center gap-2.5 rounded-xl border border-dashed border-[var(--border)] px-3 py-4 text-xs text-[var(--muted-foreground)]">
              <BookOpen className="h-3.5 w-3.5 shrink-0" />
              {t("No books are available yet")}
            </div>
          )}
          {error && (
            <p className="mt-4 flex items-center gap-1.5 text-xs text-red-600">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {error}
            </p>
          )}
        </div>
        <footer className="flex justify-end gap-2 border-t border-[var(--border)] px-5 py-4 sm:px-7">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="h-10 rounded-xl px-4 text-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-50"
          >
            {t("Cancel")}
          </button>
          <button
            type="button"
            onClick={() => selected && void importBook(selected)}
            disabled={busy || !selected}
            data-modal-initial-focus
            className="inline-flex h-10 items-center gap-2 rounded-xl bg-[var(--primary)] px-4 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-50"
          >
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {busy ? t("Importing…") : t("Import")}
          </button>
        </footer>
      </div>
    </div>
  );
}
