"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Bookmark,
  ChevronDown,
  ExternalLink,
  FolderOpen,
  Loader2,
  MessageSquare,
  NotebookPen,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  createCategory,
  deleteCategory,
  deleteNotebookEntry,
  listCategories,
  listNotebookEntries,
  removeEntryFromCategory,
  renameCategory,
  updateNotebookEntry,
  type NotebookCategory,
  type NotebookEntry,
} from "@/lib/notebook-api";

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  { ssr: false },
);

type FilterMode = "all" | "bookmarked" | "wrong";

export default function NotebookPage() {
  const { t } = useTranslation();
  const [items, setItems] = useState<NotebookEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<FilterMode>("all");
  const [activeCategoryId, setActiveCategoryId] = useState<number | null>(null);
  const [categories, setCategories] = useState<NotebookCategory[]>([]);
  const [pendingId, setPendingId] = useState<number | null>(null);

  const [showCategoryManager, setShowCategoryManager] = useState(false);
  const [newCatName, setNewCatName] = useState("");
  const [renamingCat, setRenamingCat] = useState<{ id: number; name: string } | null>(null);

  const loadCategories = useCallback(async () => {
    try {
      setCategories(await listCategories());
    } catch { /* ignore */ }
  }, []);

  const loadItems = useCallback(
    async (mode: FilterMode, catId: number | null) => {
      setRefreshing(true);
      setError(null);
      try {
        const response = await listNotebookEntries({
          bookmarked: mode === "bookmarked" ? true : undefined,
          is_correct: mode === "wrong" ? false : undefined,
          category_id: catId ?? undefined,
          limit: 200,
        });
        setItems(response.items);
        setTotal(response.total);
      } catch (err) {
        setError(String(err instanceof Error ? err.message : err));
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [],
  );

  useEffect(() => {
    void loadItems(filter, activeCategoryId);
    void loadCategories();
  }, [filter, activeCategoryId, loadItems, loadCategories]);

  const handleToggleBookmark = useCallback(
    async (item: NotebookEntry) => {
      const next = !item.bookmarked;
      setPendingId(item.id);
      try {
        await updateNotebookEntry(item.id, { bookmarked: next });
        setItems((prev) =>
          filter === "bookmarked" && !next
            ? prev.filter((e) => e.id !== item.id)
            : prev.map((e) => (e.id === item.id ? { ...e, bookmarked: next } : e)),
        );
        if (filter === "bookmarked" && !next) setTotal((p) => Math.max(0, p - 1));
      } catch { /* ignore */ }
      setPendingId(null);
    },
    [filter],
  );

  const handleDelete = useCallback(
    async (item: NotebookEntry) => {
      if (!window.confirm(t("Delete this entry?"))) return;
      setPendingId(item.id);
      try {
        await deleteNotebookEntry(item.id);
        setItems((prev) => prev.filter((e) => e.id !== item.id));
        setTotal((p) => Math.max(0, p - 1));
      } catch { /* ignore */ }
      setPendingId(null);
    },
    [t],
  );

  const handleRemoveFromCategory = useCallback(
    async (item: NotebookEntry) => {
      if (activeCategoryId === null) return;
      setPendingId(item.id);
      try {
        await removeEntryFromCategory(item.id, activeCategoryId);
        setItems((prev) => prev.filter((e) => e.id !== item.id));
        setTotal((p) => Math.max(0, p - 1));
      } catch { /* ignore */ }
      setPendingId(null);
    },
    [activeCategoryId],
  );

  const handleCreateCategory = useCallback(async () => {
    if (!newCatName.trim()) return;
    try {
      await createCategory(newCatName.trim());
      setNewCatName("");
      await loadCategories();
    } catch { /* ignore */ }
  }, [loadCategories, newCatName]);

  const handleRenameCategory = useCallback(async () => {
    if (!renamingCat || !renamingCat.name.trim()) return;
    try {
      await renameCategory(renamingCat.id, renamingCat.name.trim());
      setRenamingCat(null);
      await loadCategories();
    } catch { /* ignore */ }
  }, [loadCategories, renamingCat]);

  const handleDeleteCategory = useCallback(
    async (catId: number) => {
      if (!window.confirm(t("Delete this category?"))) return;
      try {
        await deleteCategory(catId);
        if (activeCategoryId === catId) setActiveCategoryId(null);
        await loadCategories();
      } catch { /* ignore */ }
    },
    [activeCategoryId, loadCategories, t],
  );

  const FILTERS: { mode: FilterMode; label: string }[] = [
    { mode: "all", label: "All" },
    { mode: "bookmarked", label: "Bookmarked" },
    { mode: "wrong", label: "Wrong Only" },
  ];

  return (
    <div className="h-full overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-[960px] px-6 py-8">
        {/* Header */}
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="text-[24px] font-semibold tracking-tight text-[var(--foreground)]">
              {t("Question Notebook")}
            </h1>
            <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
              {t("Review and organize quiz questions across sessions.")}
            </p>
          </div>
        </div>

        <div className={`mb-4 overflow-hidden rounded-xl border transition-colors ${showCategoryManager ? "border-[var(--border)] bg-[var(--card)]" : "border-[var(--border)]/50 bg-transparent"}`}>
          <button
            onClick={() => setShowCategoryManager((v) => !v)}
            className="flex w-full items-center justify-between px-4 py-2.5 text-[13px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/40"
          >
            <span className="flex items-center gap-2">
              <FolderOpen className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
              {t("Manage Categories")}
              {categories.length > 0 && (
                <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                  {categories.length}
                </span>
              )}
            </span>
            <ChevronDown className={`h-3.5 w-3.5 text-[var(--muted-foreground)] transition-transform duration-200 ${showCategoryManager ? "rotate-180" : ""}`} />
          </button>

          {showCategoryManager && (
            <div className="border-t border-[var(--border)] px-4 pb-4 pt-3">
              <div className="space-y-1.5">
                {categories.map((cat) => (
                  <div key={cat.id} className="flex items-center justify-between gap-2 rounded-lg bg-[var(--muted)]/30 px-3 py-2">
                    {renamingCat?.id === cat.id ? (
                      <input
                        autoFocus
                        value={renamingCat.name}
                        onChange={(e) => setRenamingCat({ ...renamingCat, name: e.target.value })}
                        onKeyDown={(e) => { if (e.key === "Enter") void handleRenameCategory(); if (e.key === "Escape") setRenamingCat(null); }}
                        onBlur={() => void handleRenameCategory()}
                        className="flex-1 rounded border border-[var(--border)] bg-[var(--background)] px-2 py-0.5 text-[12px] text-[var(--foreground)] outline-none"
                      />
                    ) : (
                      <span className="text-[12px] text-[var(--foreground)]">
                        {cat.name}
                        <span className="ml-1.5 text-[var(--muted-foreground)]">({cat.entry_count})</span>
                      </span>
                    )}
                    <div className="flex items-center gap-1">
                      <button onClick={() => setRenamingCat({ id: cat.id, name: cat.name })} className="rounded p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]">
                        <Pencil size={12} />
                      </button>
                      <button onClick={() => void handleDeleteCategory(cat.id)} className="rounded p-1 text-[var(--muted-foreground)] transition-colors hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30">
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>
                ))}
                {!categories.length && (
                  <p className="py-2 text-center text-[12px] text-[var(--muted-foreground)]">
                    {t("No categories yet.")}
                  </p>
                )}
              </div>
              <div className="mt-3 flex items-center gap-1.5">
                <input
                  value={newCatName}
                  onChange={(e) => setNewCatName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && void handleCreateCategory()}
                  placeholder={t("New category name...")}
                  className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[12px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
                />
                <button
                  onClick={() => void handleCreateCategory()}
                  disabled={!newCatName.trim()}
                  className="rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-white disabled:opacity-30"
                >
                  <Plus size={13} />
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Filter bar */}
        <div className="mb-5 flex items-center justify-between border-b border-[var(--border)]/50 pb-3">
          <div className="flex items-center gap-1 overflow-x-auto">
            {FILTERS.map(({ mode, label }) => {
              const active = filter === mode && activeCategoryId === null;
              return (
                <button
                  key={mode}
                  onClick={() => { setFilter(mode); setActiveCategoryId(null); }}
                  className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                    active
                      ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  {t(label)}
                </button>
              );
            })}
            {categories.length > 0 && (
              <span className="mx-1 text-[var(--border)]">|</span>
            )}
            {categories.map((cat) => {
              const active = activeCategoryId === cat.id;
              return (
                <button
                  key={cat.id}
                  onClick={() => { setActiveCategoryId(cat.id); setFilter("all"); }}
                  className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors ${
                    active
                      ? "bg-[var(--muted)] font-medium text-[var(--foreground)]"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  <FolderOpen size={12} />
                  {cat.name}
                </button>
              );
            })}
          </div>
          <span className="shrink-0 text-[12px] text-[var(--muted-foreground)]">
            {t("Total")}: {total}
          </span>
        </div>

        {/* Content */}
        {loading ? (
          <div className="flex min-h-[420px] items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : error ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-dashed border-red-300 text-center dark:border-red-900">
            <div className="mb-3 rounded-xl bg-red-50 p-2.5 text-red-500 dark:bg-red-950/30">
              <AlertTriangle size={18} />
            </div>
            <p className="text-[14px] font-medium text-[var(--foreground)]">
              {t("Failed to load entries")}
            </p>
            <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">{error}</p>
            <button
              onClick={() => void loadItems(filter, activeCategoryId)}
              className="mt-3 rounded-lg bg-[var(--primary)] px-4 py-1.5 text-[12px] font-medium text-white"
            >
              {t("Retry")}
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="flex min-h-[320px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
            <div className="mb-3 rounded-xl bg-[var(--muted)] p-2.5 text-[var(--muted-foreground)]">
              <NotebookPen size={18} />
            </div>
            <p className="text-[14px] font-medium text-[var(--foreground)]">
              {t("No entries yet")}
            </p>
            <p className="mt-1.5 max-w-xs text-[13px] text-[var(--muted-foreground)]">
              {t("Questions from your quizzes will appear here.")}
            </p>
          </div>
        ) : (
          <ul className="flex flex-col gap-3">
            {items.map((item) => {
              const disabled = pendingId === item.id;
              return (
                <li
                  key={item.id}
                  className={`rounded-xl border border-[var(--border)] px-5 py-4 transition-opacity ${
                    disabled ? "opacity-60" : ""
                  }`}
                >
                  {/* Question header */}
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                        {item.difficulty && (
                          <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase ${
                            item.difficulty === "hard"
                              ? "bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-400"
                              : item.difficulty === "medium"
                                ? "bg-amber-50 text-amber-600 dark:bg-amber-950/30 dark:text-amber-400"
                                : "bg-green-50 text-green-600 dark:bg-green-950/30 dark:text-green-400"
                          }`}>{item.difficulty}</span>
                        )}
                        {item.question_type && (
                          <span className="rounded-md bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--muted-foreground)]">
                            {item.question_type}
                          </span>
                        )}
                        <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-semibold ${
                          item.is_correct
                            ? "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400"
                            : "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-400"
                        }`}>
                          {item.is_correct ? t("Correct") : t("Incorrect")}
                        </span>
                      </div>
                      <div className="text-[14px] font-medium text-[var(--foreground)]">
                        <MarkdownRenderer
                          content={item.question}
                          variant="prose"
                          className="text-[14px] leading-relaxed"
                        />
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => void handleToggleBookmark(item)}
                        disabled={disabled}
                        title={item.bookmarked ? t("Remove Bookmark") : t("Bookmark")}
                        className={`rounded-lg p-1.5 transition-colors disabled:opacity-40 ${
                          item.bookmarked
                            ? "text-[var(--primary)]"
                            : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                        }`}
                      >
                        <Bookmark className="h-4 w-4" fill={item.bookmarked ? "currentColor" : "none"} />
                      </button>
                      {activeCategoryId !== null && (
                        <button
                          onClick={() => void handleRemoveFromCategory(item)}
                          disabled={disabled}
                          title={t("Remove from category")}
                          className="rounded-lg p-1.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-40"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      )}
                      <button
                        onClick={() => void handleDelete(item)}
                        disabled={disabled}
                        title={t("Delete")}
                        className="rounded-lg p-1.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-40"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>

                  {/* Options for choice questions */}
                  {item.options && Object.keys(item.options).length > 0 && (
                    <div className="mb-3 space-y-1.5">
                      {Object.entries(item.options).map(([key, text]) => {
                        const isUserAnswer = item.user_answer?.toUpperCase() === key.toUpperCase();
                        const isCorrectAnswer = item.correct_answer?.toUpperCase() === key.toUpperCase();
                        const isWrongPick = isUserAnswer && !item.is_correct;
                        return (
                          <div
                            key={key}
                            className={`flex items-start gap-2.5 rounded-lg border px-3 py-2 text-[13px] transition-colors ${
                              isCorrectAnswer
                                ? "border-green-200 bg-green-50/60 dark:border-green-900 dark:bg-green-950/20"
                                : isWrongPick
                                  ? "border-red-200 bg-red-50/60 dark:border-red-900 dark:bg-red-950/20"
                                  : "border-transparent bg-[var(--muted)]/30"
                            }`}
                          >
                            <span className={`mt-px shrink-0 font-semibold ${
                              isCorrectAnswer
                                ? "text-green-600 dark:text-green-400"
                                : isWrongPick
                                  ? "text-red-600 dark:text-red-400"
                                  : "text-[var(--muted-foreground)]"
                            }`}>
                              {key}.
                            </span>
                            <span className={`flex-1 ${
                              isCorrectAnswer || isWrongPick ? "text-[var(--foreground)]" : "text-[var(--muted-foreground)]"
                            }`}>
                              {text}
                            </span>
                            {isCorrectAnswer && (
                              <span className="mt-px shrink-0 text-[10px] font-medium text-green-600 dark:text-green-400">✓ {t("Correct")}</span>
                            )}
                            {isWrongPick && (
                              <span className="mt-px shrink-0 text-[10px] font-medium text-red-600 dark:text-red-400">✗ {t("Your pick")}</span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Answers for coding / written / fill-in questions */}
                  {(!item.options || Object.keys(item.options).length === 0) && (
                    <div className="mb-3 space-y-2 text-[13px]">
                      <div className={`rounded-lg border px-3 py-2.5 ${
                        !item.is_correct
                          ? "border-red-200/60 bg-red-50/40 dark:border-red-900/40 dark:bg-red-950/15"
                          : "border-green-200/60 bg-green-50/40 dark:border-green-900/40 dark:bg-green-950/15"
                      }`}>
                        <div className={`mb-1 text-[11px] font-medium uppercase tracking-wide ${
                          !item.is_correct
                            ? "text-red-500 dark:text-red-400"
                            : "text-green-600 dark:text-green-400"
                        }`}>
                          {t("Your Answer")} {item.is_correct ? "✓" : "✗"}
                        </div>
                        <div className="text-[var(--foreground)]">
                          {item.user_answer ? (
                            item.question_type === "coding" ? (
                              <MarkdownRenderer content={`\`\`\`python\n${item.user_answer}\n\`\`\``} variant="prose" className="text-[13px]" />
                            ) : (
                              <MarkdownRenderer content={item.user_answer} variant="prose" className="text-[13px] leading-relaxed" />
                            )
                          ) : (
                            <span className="text-[var(--muted-foreground)]">—</span>
                          )}
                        </div>
                      </div>
                      <div className="rounded-lg border border-green-200/60 bg-green-50/40 px-3 py-2.5 dark:border-green-900/40 dark:bg-green-950/15">
                        <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-green-600 dark:text-green-400">
                          {t("Reference Answer")}
                        </div>
                        <div className="text-[var(--foreground)]">
                          {item.correct_answer ? (
                            item.question_type === "coding" ? (
                              <MarkdownRenderer content={item.correct_answer.trimStart().startsWith("```") ? item.correct_answer : `\`\`\`python\n${item.correct_answer}\n\`\`\``} variant="prose" className="text-[13px]" />
                            ) : (
                              <MarkdownRenderer content={item.correct_answer} variant="prose" className="text-[13px] leading-relaxed" />
                            )
                          ) : (
                            <span className="text-[var(--muted-foreground)]">—</span>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Explanation */}
                  {item.explanation && (
                    <div className="mb-3 rounded-lg border border-blue-200/60 bg-blue-50/30 px-3 py-2.5 dark:border-blue-900/40 dark:bg-blue-950/15">
                      <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-blue-600 dark:text-blue-400">
                        {t("Explanation")}
                      </div>
                      <div className="text-[13px] leading-relaxed text-[var(--foreground)]">
                        <MarkdownRenderer content={item.explanation} variant="prose" className="text-[13px] leading-relaxed" />
                      </div>
                    </div>
                  )}

                  {/* Footer */}
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px]">
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/?session=${encodeURIComponent(item.session_id)}`}
                        className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-2.5 py-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                      >
                        <ExternalLink size={10} />
                        {item.session_title || t("Original Session")}
                      </Link>
                      {item.followup_session_id && (
                        <Link
                          href={`/?session=${encodeURIComponent(item.followup_session_id)}`}
                          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--muted)]/40 px-2.5 py-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                        >
                          <MessageSquare size={10} />
                          {t("Follow-up")}
                        </Link>
                      )}
                    </div>
                    <span className="text-[var(--muted-foreground)]">{new Date(item.created_at * 1000).toLocaleString()}</span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
