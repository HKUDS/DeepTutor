"use client";

import { useEffect, useState, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import { AlertCircle, BookOpen, Loader2, X } from "lucide-react";

import { bookApi } from "@/lib/book-api";
import type { Book } from "@/lib/book-types";
import { importFromKpTree } from "@/lib/learning-api";

import { useModalDialog } from "@/hooks/useModalDialog";

/**
 * Start a mastery path straight from a textbook.
 *
 * The empty atlas's "from your textbook" entry: list the bookshelf, and the
 * chosen book's canonical KP tree is converted server-side into the first
 * path's modules — the learner never writes a goal or an outline first.
 * Idempotent on the server, so re-picking the same book cannot wipe
 * progress that was made in the meantime.
 */
export function StartFromBookDialog({
  onClose,
  onStarted,
  returnFocusRef,
}: {
  onClose: () => void;
  onStarted: (bookId: string, moduleCount: number) => void;
  returnFocusRef: RefObject<HTMLElement | null>;
}) {
  const { t } = useTranslation();
  const [books, setBooks] = useState<Book[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useModalDialog(onClose, busyId !== null, returnFocusRef);

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

  const startFrom = async (book: Book) => {
    setBusyId(book.id);
    setError(null);
    try {
      const result = await importFromKpTree(book.id);
      onStarted(book.id, result.module_count ?? 0);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("Import failed."));
      setBusyId(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[var(--overlay)] p-0 backdrop-blur-[2px] sm:items-center sm:p-6">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="start-from-book-title"
        aria-describedby="start-from-book-description"
        tabIndex={-1}
        className="flex max-h-[92dvh] w-full max-w-2xl flex-col overflow-hidden rounded-t-[26px] border border-[var(--border)] bg-[var(--card)] shadow-2xl outline-none sm:rounded-xl"
      >
        <header className="flex items-start justify-between border-b border-[var(--border)] px-5 py-4 sm:px-7">
          <div className="min-w-0">
            <h2
              id="start-from-book-title"
              className="text-xl font-semibold tracking-tight"
            >
              {t("Start from your textbook")}
            </h2>
            <p
              id="start-from-book-description"
              className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]"
            >
              {t(
                "Pick a textbook — its own chapter tree becomes your first mastery path, no goal writing needed.",
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busyId !== null}
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
                const busy = busyId === book.id;
                const unavailable = book.status === "error";
                return (
                  <button
                    key={book.id}
                    type="button"
                    onClick={() => void startFrom(book)}
                    disabled={busyId !== null || unavailable}
                    className="flex min-h-16 items-center gap-3 rounded-xl border border-[var(--border)] p-3 text-left transition hover:bg-[var(--accent)]/60 disabled:cursor-not-allowed disabled:opacity-55"
                  >
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--muted-foreground)]/10 text-[var(--muted-foreground)]">
                      {busy ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <BookOpen className="h-4 w-4" />
                      )}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-[var(--foreground)]">
                        {book.title}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-[var(--muted-foreground)]">
                        {busy
                          ? t("Importing…")
                          : unavailable
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
      </div>
    </div>
  );
}
