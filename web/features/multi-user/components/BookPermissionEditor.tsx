"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, BookOpen, CheckCircle2, Loader2, Save } from "lucide-react";
import {
  fetchAdminBooks,
  fetchBookPermission,
  saveBookPermission,
} from "../api";
import type {
  AdminBook,
  BookPermission,
  BookPermissionLevel,
} from "../types";

const EMPTY: BookPermission = { create: true, default: "none", books: {} };

export function BookPermissionEditor({ userId }: { userId: string }) {
  const [books, setBooks] = useState<AdminBook[]>([]);
  const [permission, setPermission] = useState<BookPermission>(EMPTY);
  const [saved, setSaved] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedNow, setSavedNow] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchAdminBooks(), fetchBookPermission(userId)])
      .then(([catalog, next]) => {
        if (cancelled) return;
        setBooks(catalog);
        setPermission(next);
        setSaved(JSON.stringify(next));
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const dirty = useMemo(
    () => Boolean(saved) && saved !== JSON.stringify(permission),
    [permission, saved],
  );

  const setLevel = (bookId: string, level: BookPermissionLevel) => {
    setSavedNow(false);
    setPermission((current) => {
      const next = { ...current, books: { ...current.books } };
      // An override identical to the default carries no information.
      if (level === current.default) delete next.books[bookId];
      else next.books[bookId] = level;
      return next;
    });
  };

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const next = await saveBookPermission(userId, permission);
      setPermission(next);
      setSaved(JSON.stringify(next));
      setSavedNow(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 border-t border-[var(--border)] px-5 py-4 text-xs text-[var(--muted-foreground)]">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading book permissions…
      </div>
    );
  }

  return (
    <section className="border-t border-[var(--border)] bg-[var(--background)]/40 px-5 py-4">
      <div className="mb-3 flex items-start justify-between gap-4">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--foreground)]">
            <BookOpen className="h-4 w-4" /> Book access
          </h3>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            Shared deletion is never delegated. Reading progress and notes stay private per user.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void save()}
          disabled={!dirty || saving}
          className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1.5 text-xs font-medium text-[var(--primary-foreground)] disabled:opacity-40"
        >
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          Save
        </button>
      </div>

      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <label className="flex items-center gap-2 rounded-lg border border-[var(--border)] p-3 text-xs">
          <input
            type="checkbox"
            checked={permission.create}
            onChange={(event) => {
              setSavedNow(false);
              setPermission((current) => ({ ...current, create: event.target.checked }));
            }}
          />
          May create personal books
        </label>
        <label className="flex items-center justify-between gap-3 rounded-lg border border-[var(--border)] p-3 text-xs">
          New shared books default to
          <select
            value={permission.default}
            onChange={(event) => {
              setSavedNow(false);
              setPermission((current) => ({
                ...current,
                default: event.target.value as "none" | "read",
              }));
            }}
            className="rounded border border-[var(--border)] bg-[var(--card)] px-2 py-1"
          >
            <option value="none">No access</option>
            <option value="read">Read only</option>
          </select>
        </label>
      </div>

      <div className="max-h-64 space-y-1 overflow-y-auto">
        {books.length === 0 ? (
          <p className="rounded-lg border border-dashed border-[var(--border)] p-4 text-center text-xs text-[var(--muted-foreground)]">
            No admin books are available yet.
          </p>
        ) : (
          books.map((book) => (
            <label key={book.book_id} className="flex items-center justify-between gap-3 rounded-lg border border-[var(--border)]/60 px-3 py-2 text-xs">
              <span className="min-w-0 truncate" title={book.title}>{book.title || book.book_id}</span>
              <select
                value={permission.books[book.book_id] ?? permission.default}
                onChange={(event) => setLevel(book.book_id, event.target.value as BookPermissionLevel)}
                className="rounded border border-[var(--border)] bg-[var(--card)] px-2 py-1"
              >
                <option value="none">No access</option>
                <option value="read">Read only</option>
                <option value="edit">Collaborative edit</option>
              </select>
            </label>
          ))
        )}
      </div>

      {error ? (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-red-600"><AlertCircle className="h-3.5 w-3.5" />{error}</p>
      ) : savedNow ? (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-emerald-600"><CheckCircle2 className="h-3.5 w-3.5" />Saved</p>
      ) : dirty ? (
        <p className="mt-3 text-xs text-amber-600">Unsaved book permission changes</p>
      ) : null}
    </section>
  );
}
