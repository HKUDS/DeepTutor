"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { notify } from "@/lib/notifications";
import {
  addEntryToCategory,
  bulkLinkEntriesToCategory,
  createCategory,
  deleteCategory,
  deleteNotebookEntry,
  getQuestionBankStats,
  listCategories,
  listNotebookEntries,
  removeEntryFromCategory,
  renameCategory,
  updateNotebookEntry,
  type NotebookCategory,
  type NotebookEntry,
  type QuestionBankStats,
} from "@/lib/notebook-api";

/**
 * What the learner is currently looking at.
 *
 * A discriminated union rather than two independent pieces of state: a
 * filter and a category are two views of the same axis, and holding them
 * separately makes "wrong answers, but also inside category 3, but also
 * uncategorized" representable when it is not a real thing.
 */
export type BankScope =
  | { kind: "all" | "wrong" | "bookmarked" | "uncategorized" }
  | { kind: "category"; categoryId: number };

export type BankSort = "recent" | "oldest";

/** Entries fetched per page. The bank is a review surface, not a feed. */
const PAGE_SIZE = 60;
const SEARCH_DEBOUNCE_MS = 250;

export const DEFAULT_SCOPE: BankScope = { kind: "all" };

function scopeToFilter(scope: BankScope, search: string, sort: BankSort) {
  return {
    category_id: scope.kind === "category" ? scope.categoryId : undefined,
    uncategorized: scope.kind === "uncategorized" || undefined,
    bookmarked: scope.kind === "bookmarked" ? true : undefined,
    is_correct: scope.kind === "wrong" ? false : undefined,
    search: search || undefined,
    sort,
    limit: PAGE_SIZE,
  };
}

export interface QuestionBankController {
  items: NotebookEntry[];
  total: number;
  categories: NotebookCategory[];
  stats: QuestionBankStats;
  scope: BankScope;
  sort: BankSort;
  searchInput: string;
  loading: boolean;
  /** True while re-fetching an already-rendered list (keeps content visible). */
  refreshing: boolean;
  error: string | null;
  pendingIds: ReadonlySet<number>;
  selectedIds: ReadonlySet<number>;

  setScope: (scope: BankScope) => void;
  setSort: (sort: BankSort) => void;
  setSearchInput: (value: string) => void;
  refresh: () => Promise<void>;

  toggleSelected: (id: number) => void;
  selectAll: () => void;
  clearSelection: () => void;

  // Mutations resolve to whether the write landed. Failures are reported
  // once, as a toast, from inside the hook — the boolean is for the caller's
  // own UI decisions (keep the menu open, keep the typed name).
  toggleBookmark: (entry: NotebookEntry) => Promise<boolean>;
  removeEntry: (entry: NotebookEntry) => Promise<boolean>;
  fileEntries: (ids: number[], categoryId: number) => Promise<boolean>;
  unfileEntries: (ids: number[], categoryId: number) => Promise<boolean>;
  fileIntoNewCategory: (ids: number[], name: string) => Promise<boolean>;

  addCategory: (name: string) => Promise<boolean>;
  renameExistingCategory: (id: number, name: string) => Promise<boolean>;
  removeCategory: (id: number) => Promise<boolean>;
}

const EMPTY_STATS: QuestionBankStats = {
  total: 0,
  wrong: 0,
  bookmarked: 0,
  uncategorized: 0,
};

/**
 * Owns every piece of question-bank state so the views stay presentational.
 *
 * Two rules keep the surface honest under mutation:
 *  - counts (`stats`, category `entry_count`) are re-read from the server
 *    after any write, never patched locally, because filing one entry moves
 *    several counters at once;
 *  - a re-fetch never blanks the list — `refreshing` dims it instead, so
 *    filing a question does not make the page jump.
 */
export function useQuestionBank(): QuestionBankController {
  const [items, setItems] = useState<NotebookEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [categories, setCategories] = useState<NotebookCategory[]>([]);
  const [stats, setStats] = useState<QuestionBankStats>(EMPTY_STATS);
  const [scope, setScopeState] = useState<BankScope>(DEFAULT_SCOPE);
  const [sort, setSort] = useState<BankSort>("recent");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingIds, setPendingIds] = useState<ReadonlySet<number>>(new Set());
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<number>>(
    new Set(),
  );

  const loadedOnce = useRef(false);
  // Guards against an older in-flight list response overwriting a newer one
  // when the learner clicks through filters faster than the network answers.
  const requestSeq = useRef(0);

  useEffect(() => {
    const timer = setTimeout(
      () => setSearch(searchInput.trim()),
      SEARCH_DEBOUNCE_MS,
    );
    return () => clearTimeout(timer);
  }, [searchInput]);

  const loadEntries = useCallback(async () => {
    const seq = ++requestSeq.current;
    if (loadedOnce.current) setRefreshing(true);
    setError(null);
    try {
      const response = await listNotebookEntries(
        scopeToFilter(scope, search, sort),
      );
      if (seq !== requestSeq.current) return;
      setItems(response.items);
      setTotal(response.total);
      // Converge the selection onto the new rows: searching, re-sorting or a
      // refresh after a write can all drop a selected row out of view, and a
      // bulk action must never reach something off screen.
      const visible = new Set(response.items.map((item) => item.id));
      setSelectedIds((prev) => {
        if (prev.size === 0) return prev;
        const next = new Set([...prev].filter((id) => visible.has(id)));
        return next.size === prev.size ? prev : next;
      });
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (seq === requestSeq.current) {
        loadedOnce.current = true;
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [scope, search, sort]);

  const loadMeta = useCallback(async () => {
    const [nextCategories, nextStats] = await Promise.allSettled([
      listCategories(),
      getQuestionBankStats(),
    ]);
    if (nextCategories.status === "fulfilled")
      setCategories(nextCategories.value);
    if (nextStats.status === "fulfilled") setStats(nextStats.value);
  }, []);

  useEffect(() => {
    void loadEntries();
  }, [loadEntries]);

  useEffect(() => {
    void loadMeta();
  }, [loadMeta]);

  // Selection is scoped to what is on screen: switching filters must not
  // leave invisible rows staged for a bulk action.
  const setScope = useCallback((next: BankScope) => {
    setSelectedIds(new Set());
    setScopeState(next);
  }, []);

  const refresh = useCallback(async () => {
    await Promise.all([loadEntries(), loadMeta()]);
  }, [loadEntries, loadMeta]);

  /**
   * Run a write and report it if it fails.
   *
   * Every mutation here used to swallow its error, so a rejected rename or
   * a duplicate category name looked exactly like a no-op click. The server
   * sends a reason; the learner should get it.
   */
  const attempt = useCallback(async (action: () => Promise<void>) => {
    try {
      await action();
      return true;
    } catch (err) {
      notify(err instanceof Error ? err.message : String(err), {
        tone: "error",
      });
      return false;
    }
  }, []);

  const withPending = useCallback(
    async (ids: number[], action: () => Promise<void>) => {
      setPendingIds((prev) => new Set([...prev, ...ids]));
      try {
        return await attempt(action);
      } finally {
        setPendingIds((prev) => {
          const next = new Set(prev);
          ids.forEach((id) => next.delete(id));
          return next;
        });
      }
    },
    [attempt],
  );

  const toggleSelected = useCallback((id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(items.map((item) => item.id)));
  }, [items]);

  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);

  const toggleBookmark = useCallback(
    async (entry: NotebookEntry) => {
      const next = !entry.bookmarked;
      return withPending([entry.id], async () => {
        await updateNotebookEntry(entry.id, { bookmarked: next });
        // Optimistic on the row itself; the counters come back from refresh.
        setItems((prev) =>
          prev.map((item) =>
            item.id === entry.id ? { ...item, bookmarked: next } : item,
          ),
        );
        await refresh();
      });
    },
    [refresh, withPending],
  );

  const removeEntry = useCallback(
    async (entry: NotebookEntry) => {
      return withPending([entry.id], async () => {
        await deleteNotebookEntry(entry.id);
        setSelectedIds((prev) => {
          const next = new Set(prev);
          next.delete(entry.id);
          return next;
        });
        await refresh();
      });
    },
    [refresh, withPending],
  );

  const fileEntries = useCallback(
    async (ids: number[], categoryId: number) => {
      if (!ids.length) return false;
      return withPending(ids, async () => {
        // The single-entry endpoint 404s on a stale id; the bulk one reports
        // 0 changed. For a one-row action the sharper error is worth the
        // separate call.
        if (ids.length === 1) await addEntryToCategory(ids[0], categoryId);
        else await bulkLinkEntriesToCategory(ids, categoryId, true);
        await refresh();
      });
    },
    [refresh, withPending],
  );

  const unfileEntries = useCallback(
    async (ids: number[], categoryId: number) => {
      if (!ids.length) return false;
      return withPending(ids, async () => {
        if (ids.length === 1) await removeEntryFromCategory(ids[0], categoryId);
        else await bulkLinkEntriesToCategory(ids, categoryId, false);
        await refresh();
      });
    },
    [refresh, withPending],
  );

  const fileIntoNewCategory = useCallback(
    async (ids: number[], name: string) => {
      const trimmed = name.trim();
      if (!trimmed) return false;
      return attempt(async () => {
        const created = await createCategory(trimmed);
        if (ids.length) await fileEntries(ids, created.id);
        else await loadMeta();
      });
    },
    [attempt, fileEntries, loadMeta],
  );

  const addCategory = useCallback(
    async (name: string) => {
      const trimmed = name.trim();
      if (!trimmed) return false;
      return attempt(async () => {
        await createCategory(trimmed);
        await loadMeta();
      });
    },
    [attempt, loadMeta],
  );

  const renameExistingCategory = useCallback(
    async (id: number, name: string) => {
      const trimmed = name.trim();
      if (!trimmed) return false;
      return attempt(async () => {
        await renameCategory(id, trimmed);
        await refresh();
      });
    },
    [attempt, refresh],
  );

  const removeCategory = useCallback(
    async (id: number) => {
      return attempt(async () => {
        await deleteCategory(id);
        // Deleting the category being viewed would otherwise leave the list
        // filtered by an id the server no longer knows.
        setScopeState((prev) =>
          prev.kind === "category" && prev.categoryId === id
            ? DEFAULT_SCOPE
            : prev,
        );
        await refresh();
      });
    },
    [attempt, refresh],
  );

  return useMemo(
    () => ({
      items,
      total,
      categories,
      stats,
      scope,
      sort,
      searchInput,
      loading,
      refreshing,
      error,
      pendingIds,
      selectedIds,
      setScope,
      setSort,
      setSearchInput,
      refresh,
      toggleSelected,
      selectAll,
      clearSelection,
      toggleBookmark,
      removeEntry,
      fileEntries,
      unfileEntries,
      fileIntoNewCategory,
      addCategory,
      renameExistingCategory,
      removeCategory,
    }),
    [
      items,
      total,
      categories,
      stats,
      scope,
      sort,
      searchInput,
      loading,
      refreshing,
      error,
      pendingIds,
      selectedIds,
      setScope,
      refresh,
      toggleSelected,
      selectAll,
      clearSelection,
      toggleBookmark,
      removeEntry,
      fileEntries,
      unfileEntries,
      fileIntoNewCategory,
      addCategory,
      renameExistingCategory,
      removeCategory,
    ],
  );
}
