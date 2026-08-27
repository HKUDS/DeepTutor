"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Loader2, MessageSquare } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useTranslation } from "react-i18next";

import { BookApiError, bookApi, type BookWsEvent } from "@/lib/book-api";
import type {
  Block,
  BlockType,
  Book,
  BookDepth,
  BookDetail,
  BookProposal,
  Page,
  Spine,
  LearningCapture,
} from "@/lib/book-types";
import {
  RESET_BOOK_PROGRESS,
  emptyBookProgress,
  progressHasActivity,
  progressIsComplete,
  reduceBookEvent,
} from "@/lib/book-progress";
import {
  bookEventKind,
  bookEventPageId,
  useBookStream,
} from "@/lib/use-book-stream";

import BookChatPanel from "./components/BookChatPanel";
import BookCreator from "./components/BookCreator";
import BookHealthBanner from "./components/BookHealthBanner";
import BookLibrary from "./components/BookLibrary";
import BookPausedBanner from "./components/BookPausedBanner";
import BookProgressTimeline from "./components/BookProgressTimeline";
import BookSidebar from "./components/BookSidebar";
import PageReader from "./components/PageReader";
import LearningCapturePanel from "./components/LearningCapturePanel";
import SpineEditor from "./components/SpineEditor";
import type { QuizAttemptArgs } from "./components/blocks/QuizBlock";

type View = "list" | "creator" | "spine" | "reader";

// Blocks land one at a time during compilation. Coalescing a burst into a
// single fetch keeps a page that is actively generating from issuing one
// request per block, while still feeling immediate to a reader watching it.
const PAGE_REFRESH_DEBOUNCE_MS = 250;

// Book-level events arrive in bursts too — several stages finishing together,
// or the whole recent history replayed when a subscriber (re)connects. One
// burst should cost one refresh, not one per event.
const BOOK_REFRESH_DEBOUNCE_MS = 300;

/** A page fetched as a summary has its blocks stripped; hydrate before reading. */
function needsHydration(page: Page | null): boolean {
  return !!page && page.blocks.length === 0 && (page.block_count ?? 0) > 0;
}

/** Events that only change one chapter — refetch that page alone. */
const PAGE_SCOPED_EVENTS = new Set([
  "page_planned",
  "page_compile_started",
  "block_ready",
  "block_error",
  "page_compiled",
]);

/** Events that change the book itself — chapter list, status, or both. */
const BOOK_SCOPED_EVENTS = new Set([
  "spine_ready",
  "overview_ready",
  "book_ready",
  "compilation_paused",
]);

export default function BookPage() {
  // `useSearchParams()` requires a Suspense boundary during static prerender
  // (Next.js CSR bailout). Wrap the actual page implementation here so the
  // production build (`next build`) doesn't fail prerendering `/book`.
  return (
    <Suspense
      fallback={
        <div className="flex h-full w-full items-center justify-center text-[var(--muted-foreground)]">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" /> <BookLoadingText />
        </div>
      }
    >
      <BookPageInner />
    </Suspense>
  );
}

function BookLoadingText() {
  const { t } = useTranslation();
  return <>{t("Loading…")}</>;
}

function BookPageInner() {
  const { t } = useTranslation();
  const router = useRouter();
  const [books, setBooks] = useState<Book[]>([]);
  const [canCreateBook, setCanCreateBook] = useState(true);
  const [loadingBooks, setLoadingBooks] = useState(false);
  const [view, setView] = useState<View>("list");

  const [selectedBookId, setSelectedBookId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BookDetail | null>(null);
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);

  // Creator-stage state
  const [creating, setCreating] = useState(false);
  const [confirmingProposal, setConfirmingProposal] = useState(false);
  const [pendingProposal, setPendingProposal] = useState<BookProposal | null>(
    null,
  );
  const [pendingBook, setPendingBook] = useState<Book | null>(null);

  // Spine-stage state
  const [confirmingSpine, setConfirmingSpine] = useState(false);

  // Page compile state
  const [compilingPageId, setCompilingPageId] = useState<string | null>(null);

  // Phase 3 state
  const [pendingDeepDiveTopic, setPendingDeepDiveTopic] = useState<
    string | null
  >(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [rebuildingBook, setRebuildingBook] = useState(false);
  const [resumingBook, setResumingBook] = useState(false);
  const [supplementingBlockId, setSupplementingBlockId] = useState<
    string | null
  >(null);
  const [learningCaptures, setLearningCaptures] = useState<LearningCapture[]>(
    [],
  );
  const [loadingLearningCaptures, setLoadingLearningCaptures] = useState(false);

  // Phase 5 — live BookEngine progress timeline state.
  const [progress, dispatchProgress] = useReducer(
    reduceBookEvent,
    null,
    emptyBookProgress,
  );

  // ── Data loaders ───────────────────────────────────────────────────

  /** Run a mutation, surfacing failures instead of dropping them. */
  const guard = useCallback(
    async (action: string, run: () => Promise<void>): Promise<void> => {
      try {
        await run();
      } catch (err) {
        if (
          err instanceof BookApiError &&
          err.status === 409 &&
          selectedBookId
        ) {
          try {
            const latest = await bookApi.get(selectedBookId, {
              includeBlocks: false,
            });
            setDetail(latest);
          } catch {
            // Keep the original conflict as the actionable error.
          }
        }
        const reason = err instanceof Error ? err.message : String(err);
        notify(t("{{action}} failed: {{reason}}", { action, reason }), {
          tone: "error",
          durationMs: 8000,
        });
        console.error(`${action} failed:`, err);
      }
    },
    [selectedBookId, t],
  );

  const refreshBooks = useCallback(async () => {
    setLoadingBooks(true);
    try {
      const data = await bookApi.list();
      setBooks(data.books);
      setCanCreateBook(data.can_create);
    } finally {
      setLoadingBooks(false);
    }
  }, []);

  /**
   * Load a book without its block payloads.
   *
   * Only the page being read needs its blocks; fetching every page's rendered
   * content to draw a sidebar meant a multi-chapter book cost hundreds of
   * kilobytes per refresh. `hydratePage` fills in the one page that matters.
   */
  const loadBookDetail = useCallback(async (id: string) => {
    const data = await bookApi.get(id, { includeBlocks: false });
    setDetail(data);
    return data;
  }, []);

  /** Replace one page in-place, leaving the rest of the book untouched. */
  const mergePage = useCallback((page: Page) => {
    setDetail((current) => {
      if (!current || current.book.id !== page.book_id) return current;
      const index = current.pages.findIndex((p) => p.id === page.id);
      if (index < 0) return current;
      const pages = [...current.pages];
      pages[index] = page;
      return { ...current, pages };
    });
  }, []);

  const applyBookRevision = useCallback((revision: number) => {
    setDetail((current) =>
      current ? { ...current, book: { ...current.book, revision } } : current,
    );
  }, []);

  const hydratePage = useCallback(
    async (pageId: string) => {
      if (!selectedBookId) return;
      try {
        const { page } = await bookApi.getPage(selectedBookId, pageId);
        mergePage(page);
      } catch (err) {
        console.error("hydratePage failed:", err);
      }
    },
    [selectedBookId, mergePage],
  );

  const refreshLearningCaptures = useCallback(
    async (bookId: string) => {
      setLoadingLearningCaptures(true);
      try {
        const { captures } = await bookApi.listLearningCaptures(bookId);
        setLearningCaptures(captures);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        notify(
          t("Could not load learning captures: {{message}}", { message: msg }),
          {
            tone: "error",
            durationMs: 6000,
          },
        );
        setLearningCaptures([]);
      } finally {
        setLoadingLearningCaptures(false);
      }
    },
    [t],
  );

  // Debounced per page, so a burst of block events costs one fetch.
  const pageRefreshTimers = useRef(
    new Map<string, ReturnType<typeof setTimeout>>(),
  );
  const schedulePageRefresh = useCallback(
    (pageId: string) => {
      const timers = pageRefreshTimers.current;
      const pending = timers.get(pageId);
      if (pending) clearTimeout(pending);
      timers.set(
        pageId,
        setTimeout(() => {
          timers.delete(pageId);
          void hydratePage(pageId);
        }, PAGE_REFRESH_DEBOUNCE_MS),
      );
    },
    [hydratePage],
  );

  const bookRefreshTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const scheduleBookRefresh = useCallback(() => {
    if (bookRefreshTimer.current) clearTimeout(bookRefreshTimer.current);
    bookRefreshTimer.current = setTimeout(() => {
      bookRefreshTimer.current = undefined;
      if (selectedBookId) void loadBookDetail(selectedBookId);
      void refreshBooks();
    }, BOOK_REFRESH_DEBOUNCE_MS);
  }, [selectedBookId, loadBookDetail, refreshBooks]);

  useEffect(() => {
    const timers = pageRefreshTimers.current;
    return () => {
      timers.forEach((timer) => clearTimeout(timer));
      timers.clear();
      if (bookRefreshTimer.current) clearTimeout(bookRefreshTimer.current);
    };
  }, []);

  useEffect(() => {
    void refreshBooks();
  }, [refreshBooks]);

  // The generation timeline describes one book's run. Clear it when the reader
  // moves to another book, or the previous book's stages stay on screen.
  useEffect(() => {
    dispatchProgress(RESET_BOOK_PROGRESS);
  }, [selectedBookId]);

  // ── Live event handling ────────────────────────────────────────────

  const handleBookEvent = useCallback(
    (event: BookWsEvent) => {
      dispatchProgress(event);

      const kind = bookEventKind(event);
      const pageId = bookEventPageId(event);

      // Page-scoped: refetch just that chapter. Refetching the whole book on
      // every block was the single most expensive thing this screen did.
      if (pageId && PAGE_SCOPED_EVENTS.has(kind)) {
        schedulePageRefresh(pageId);
        return;
      }

      // Book-scoped: the chapter list or the book's own state moved.
      if (BOOK_SCOPED_EVENTS.has(kind)) {
        scheduleBookRefresh();
      }

      // Deliberately no toast here: `compilation_paused` is replayed to every
      // new subscriber, so a book that was paused once and resumed would pop a
      // stale alert on each reconnect. Pausing is durable state, and
      // BookPausedBanner renders it from `book.status`, which the refresh
      // above has just brought up to date.
    },
    [scheduleBookRefresh, schedulePageRefresh],
  );

  // One connection per open book, independent of any action in flight —
  // background compilation keeps streaming long after the call that queued it.
  useBookStream(selectedBookId, handleBookEvent);

  // Ideation runs before the book exists, so it has no stream of its own to
  // subscribe to; those events arrive on the creating socket instead.
  const handleCreationEvent = useCallback((event: BookWsEvent) => {
    dispatchProgress(event);
  }, []);

  // ── Selectors ──────────────────────────────────────────────────────

  const selectedPage: Page | null = useMemo(() => {
    if (!detail || !selectedPageId) return null;
    return detail.pages.find((p) => p.id === selectedPageId) || null;
  }, [detail, selectedPageId]);

  // Reading order is the page order — the sidebar shows the same sequence.
  const pageNeighbours = useMemo(() => {
    if (!detail || !selectedPageId) return { previous: null, next: null };
    const index = detail.pages.findIndex((p) => p.id === selectedPageId);
    if (index < 0) return { previous: null, next: null };
    return {
      previous: detail.pages[index - 1] || null,
      next: detail.pages[index + 1] || null,
    };
  }, [detail, selectedPageId]);

  const selectedPageChatSessionId = useMemo(() => {
    if (!detail?.book || !selectedPage) return null;
    const sessions = detail.book.metadata?.page_chat_sessions;
    return sessions?.[selectedPage.id] || null;
  }, [detail?.book, selectedPage]);

  const canEditBook = detail?.book.can_edit !== false;
  const expectedRevision = detail?.book.revision;

  // ── Handlers ───────────────────────────────────────────────────────

  const handleNewBook = () => {
    if (!canCreateBook) return;
    setSelectedBookId(null);
    setDetail(null);
    setPendingBook(null);
    setPendingProposal(null);
    setSelectedPageId(null);
    setView("creator");
  };

  // Defined after handleSelectBook below.
  const lastDeepLinkedBookId = useRef<string | null>(null);

  const handleSelectBook = useCallback(
    async (id: string | null, openPageId?: string | null) => {
      if (!id) {
        setSelectedBookId(null);
        setDetail(null);
        setView("list");
        return;
      }
      setSelectedBookId(id);
      const data = await loadBookDetail(id);
      const hasReadableContent = data.pages.some(
        (p) => p.status !== "pending" || (p.block_count ?? p.blocks.length) > 0,
      );
      const canEdit = data.book.can_edit !== false;
      if (canEdit && data.book.status === "draft" && data.book.proposal) {
        setPendingBook(data.book);
        setPendingProposal(data.book.proposal);
        setView("creator");
      } else if (
        canEdit &&
        data.book.status === "spine_ready" &&
        data.spine &&
        !hasReadableContent
      ) {
        // Spine confirmed but nothing built yet — the editor is still the right
        // place. Once any chapter exists, the reader is.
        setView("spine");
      } else {
        // Resume where the reader left off — that's what `current_page_id` is
        // for, and until now nothing ever read it.
        const requested =
          (openPageId && data.pages.find((p) => p.id === openPageId)) || null;
        const resumed =
          data.pages.find((p) => p.id === data.progress.current_page_id) ||
          null;
        const firstReady = data.pages.find((p) => p.status === "ready") || null;
        const target =
          requested || resumed || firstReady || data.pages[0] || null;
        setSelectedPageId(target?.id || null);
        setView("reader");
      }
    },
    [loadBookDetail],
  );

  // Deep links: /book?book=<id>[&page=<id>] — used by the global sidebar and
  // by the overview chapter index (which previously pointed at /book/<id>, a
  // route that does not exist, so every entry 404'd).
  const searchParams = useSearchParams();
  const requestedBookId = searchParams?.get("book") || null;
  const requestedPageId = searchParams?.get("page") || null;
  useEffect(() => {
    if (!requestedBookId) return;
    if (requestedBookId === selectedBookId) return;
    if (requestedBookId === lastDeepLinkedBookId.current) return;
    lastDeepLinkedBookId.current = requestedBookId;
    void handleSelectBook(requestedBookId, requestedPageId);
  }, [requestedBookId, requestedPageId, selectedBookId, handleSelectBook]);

  useEffect(() => {
    if (view !== "reader" || !selectedBookId) {
      if (!selectedBookId) setLearningCaptures([]);
      return;
    }
    void refreshLearningCaptures(selectedBookId);
  }, [view, selectedBookId, refreshLearningCaptures]);

  const handleDeleteBook = async (id: string) =>
    guard("Delete book", async () => {
      // The library card already requires a second click to confirm.
      await bookApi.delete(id);
      if (selectedBookId === id) {
        setSelectedBookId(null);
        setDetail(null);
        setView("list");
      }
      await refreshBooks();
    });

  const handleResumeBook = async () => {
    if (!detail || !canEditBook) return;
    setResumingBook(true);
    try {
      await bookApi.resume(detail.book.id, expectedRevision);
      await loadBookDetail(detail.book.id);
      await refreshBooks();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      notify(t("Could not resume: {{message}}", { message: msg }), {
        tone: "error",
        durationMs: 8000,
      });
    } finally {
      setResumingBook(false);
    }
  };

  const handleRebuildBook = async () =>
    guard("Rebuild book", async () => {
      if (!detail || !canEditBook) return;
      setRebuildingBook(true);
      try {
        await bookApi.rebuild(detail.book.id, true, expectedRevision);
        const refreshed = await loadBookDetail(detail.book.id);
        setSelectedPageId(refreshed.pages[0]?.id || null);
        setView("reader");
        await refreshBooks();
      } finally {
        setRebuildingBook(false);
      }
    });

  const handleCreate = async (payload: {
    user_intent: string;
    chat_session_id: string;
    chat_selections: Array<{ session_id: string; message_ids: number[] }>;
    knowledge_bases: string[];
    notebook_refs: Array<Record<string, unknown>>;
    question_categories: number[];
    question_entries: number[];
    language: string;
    depth: BookDepth;
  }) => {
    setCreating(true);
    try {
      const result = await bookApi.create(payload, handleCreationEvent);
      setPendingBook(result.book);
      setPendingProposal(result.proposal);
      setSelectedBookId(result.book.id);
      await refreshBooks();
    } finally {
      setCreating(false);
    }
  };

  const handleConfirmProposal = async (edited: BookProposal) => {
    if (!pendingBook || pendingBook.can_edit === false) return;
    setConfirmingProposal(true);
    try {
      // No per-action event callback: the book now has a stream of its own,
      // and `useBookStream` is already listening. Passing one too would feed
      // the timeline every event twice.
      const result = await bookApi.confirmProposal(
        pendingBook.id,
        edited,
        pendingBook.revision,
      );
      setPendingBook(result.book);
      setPendingProposal(null);
      await loadBookDetail(result.book.id);
      setView("spine");
      await refreshBooks();
    } finally {
      setConfirmingProposal(false);
    }
  };

  const handleConfirmSpine = async (spine: Spine, autoCompile: boolean) => {
    if (!detail || !canEditBook) return;
    setConfirmingSpine(true);
    try {
      await bookApi.confirmSpine(
        detail.book.id,
        spine,
        autoCompile,
        expectedRevision,
      );
      const refreshed = await loadBookDetail(detail.book.id);
      const firstPage = refreshed.pages[0] || null;
      setSelectedPageId(firstPage?.id || null);
      setView("reader");
      if (firstPage && canEditBook) {
        void compilePage(firstPage.id);
      }
      await refreshBooks();
    } finally {
      setConfirmingSpine(false);
    }
  };

  const compilePage = useCallback(
    async (pageId: string, force = false) => {
      if (!selectedBookId || !canEditBook) return;
      setCompilingPageId(pageId);
      try {
        // Progress arrives on the book's stream; this call just awaits the
        // finished page. The engine coalesces it with any run already in
        // flight, so opening a page the worker reached first is free.
        const { page, book_revision } = await bookApi.compilePage(
          selectedBookId,
          pageId,
          force,
          expectedRevision,
        );
        applyBookRevision(book_revision);
        mergePage(page);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        notify(t("Compile failed: {{message}}", { message: msg }), {
          tone: "error",
          durationMs: 8000,
        });
        console.error("compilePage failed:", err);
        void loadBookDetail(selectedBookId);
      } finally {
        setCompilingPageId((current) => (current === pageId ? null : current));
      }
    },
    [
      selectedBookId,
      canEditBook,
      expectedRevision,
      applyBookRevision,
      mergePage,
      loadBookDetail,
      t,
    ],
  );

  const handleSelectPage = useCallback(
    (pageId: string) => {
      setSelectedPageId(pageId);
      if (!detail) return;

      const page = detail.pages.find((p) => p.id === pageId);
      if (!page) return;
      // Hydration is handled by the reader effect below, which fires for
      // every route into a page — including the one that opens the book.
      if (
        canEditBook &&
        page.status !== "ready" &&
        page.status !== "generating"
      ) {
        void compilePage(pageId);
      }
    },
    [detail, canEditBook, compilePage],
  );

  // A ?page= change on a book that is already open just moves the reader.
  const lastDeepLinkedPageId = useRef<string | null>(null);
  useEffect(() => {
    if (!requestedPageId || !requestedBookId) return;
    if (requestedBookId !== selectedBookId) return;
    if (requestedPageId === lastDeepLinkedPageId.current) return;
    lastDeepLinkedPageId.current = requestedPageId;
    if (requestedPageId !== selectedPageId) handleSelectPage(requestedPageId);
    // Consume the parameter so following the same link again re-triggers it.
    router.replace(`/book?book=${encodeURIComponent(requestedBookId)}`, {
      scroll: false,
    });
  }, [
    requestedPageId,
    requestedBookId,
    selectedBookId,
    selectedPageId,
    handleSelectPage,
    router,
  ]);

  // Opening a book lands on a page without going through `handleSelectPage`,
  // so hydrate and record the visit here too. The ref keeps recording a visit
  // from re-triggering itself when the updated progress comes back.
  const recordedVisitRef = useRef<string | null>(null);
  useEffect(() => {
    if (view !== "reader" || !selectedBookId || !selectedPage) return;
    if (needsHydration(selectedPage)) void hydratePage(selectedPage.id);

    const key = `${selectedBookId}:${selectedPage.id}`;
    if (recordedVisitRef.current === key) return;
    recordedVisitRef.current = key;
    const bookId = selectedBookId;
    void bookApi
      .markVisited(bookId, selectedPage.id)
      .then(({ progress }) =>
        setDetail((current) =>
          current && current.book.id === bookId
            ? { ...current, progress }
            : current,
        ),
      )
      .catch(() => {
        // Position tracking is best-effort.
      });
  }, [view, selectedBookId, selectedPage, hydratePage]);

  const handleUpdateBody = async (block: Block, body: string) => {
    if (!detail || !selectedPage) return;
    const pageId = selectedPage.id;
    try {
      const { book_revision } = await bookApi.updateBlock({
        book_id: detail.book.id,
        page_id: pageId,
        block_id: block.id,
        body,
        expected_revision: expectedRevision,
      });
      applyBookRevision(book_revision);
      await hydratePage(pageId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      notify(t("Could not save your edit: {{message}}", { message: msg }), {
        tone: "error",
        durationMs: 8000,
      });
      if (err instanceof BookApiError && err.status === 409) {
        await loadBookDetail(detail.book.id);
      }
      throw err;
    }
  };

  const handleToggleBookmark = async () =>
    guard("Bookmark", async () => {
      if (!detail || !selectedPage) return;
      const bookId = detail.book.id;
      const { progress } = await bookApi.toggleBookmark(
        bookId,
        selectedPage.id,
      );
      setDetail((current) =>
        current && current.book.id === bookId
          ? { ...current, progress }
          : current,
      );
    });

  const handleRegenerateBlock = async (block: Block) => {
    if (!detail || !selectedPage) return;
    const pageId = selectedPage.id;
    try {
      const { book_revision } = await bookApi.regenerateBlock(
        detail.book.id,
        pageId,
        block.id,
        undefined,
        expectedRevision,
      );
      applyBookRevision(book_revision);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      notify(t("Regenerate block failed: {{message}}", { message: msg }), {
        tone: "error",
        durationMs: 8000,
      });
      console.error("regenerateBlock failed:", err);
    } finally {
      await hydratePage(pageId);
    }
  };

  const handleDeleteBlock = async (block: Block) =>
    guard("Delete block", async () => {
      if (!detail || !selectedPage) return;
      const { book_revision } = await bookApi.deleteBlock(
        detail.book.id,
        selectedPage.id,
        block.id,
        expectedRevision,
      );
      applyBookRevision(book_revision);
      await hydratePage(selectedPage.id);
    });

  const handleMoveBlock = async (block: Block, direction: "up" | "down") =>
    guard("Move block", async () => {
      if (!detail || !selectedPage) return;
      const idx = selectedPage.blocks.findIndex((b) => b.id === block.id);
      if (idx < 0) return;
      const newPos = direction === "up" ? idx - 1 : idx + 1;
      if (newPos < 0 || newPos >= selectedPage.blocks.length) return;
      const { book_revision } = await bookApi.moveBlock(
        detail.book.id,
        selectedPage.id,
        block.id,
        newPos,
        expectedRevision,
      );
      applyBookRevision(book_revision);
      await hydratePage(selectedPage.id);
    });

  const handleChangeBlockType = async (block: Block, newType: BlockType) =>
    guard("Change block type", async () => {
      if (!detail || !selectedPage) return;
      const { book_revision } = await bookApi.changeBlockType({
        book_id: detail.book.id,
        page_id: selectedPage.id,
        block_id: block.id,
        new_type: newType,
        expected_revision: expectedRevision,
      });
      applyBookRevision(book_revision);
      await hydratePage(selectedPage.id);
    });

  const handleInsertBlock = async (block_type: BlockType) =>
    guard("Insert block", async () => {
      if (!detail || !selectedPage) return;
      const { book_revision } = await bookApi.insertBlock({
        book_id: detail.book.id,
        page_id: selectedPage.id,
        block_type,
        expected_revision: expectedRevision,
      });
      applyBookRevision(book_revision);
      await hydratePage(selectedPage.id);
    });

  const handleDeepDive = async (topic: string, blockId: string) =>
    guard("Deep dive", async () => {
      if (!detail || !selectedPage) return;
      setPendingDeepDiveTopic(topic);
      try {
        const result = await bookApi.deepDive({
          book_id: detail.book.id,
          parent_page_id: selectedPage.id,
          topic,
          block_id: blockId,
          expected_revision: expectedRevision,
        });
        applyBookRevision(result.book_revision);
        // A deep dive adds a page, so the chapter list itself changed.
        const refreshed = await loadBookDetail(detail.book.id);
        const newPage = refreshed.pages.find((p) => p.id === result.page.id);
        if (newPage) {
          setSelectedPageId(newPage.id);
          mergePage(result.page);
        }
      } finally {
        setPendingDeepDiveTopic(null);
      }
    });

  const handleQuizAttempt = async (block: Block, args: QuizAttemptArgs) =>
    guard("Record answer", async () => {
      if (!detail || !selectedPage) return;
      const bookId = detail.book.id;
      const { progress } = await bookApi.recordQuizAttempt({
        book_id: bookId,
        page_id: selectedPage.id,
        block_id: block.id,
        question_id: args.questionId,
        user_answer: args.userAnswer,
        is_correct: args.isCorrect,
      });
      setDetail((current) =>
        current && current.book.id === bookId
          ? { ...current, progress }
          : current,
      );
    });

  /**
   * Add a remediation callout + explanation + easier quiz for a topic.
   *
   * Explicitly requested, never automatic. This grows the page by three
   * generated blocks, and having that happen unannounced under the reader —
   * once per wrong click, with nothing stopping a second round — was both
   * startling and expensive.
   */
  const handleRequestSupplement = async (block: Block) => {
    if (!detail || !selectedPage) return;
    const pageId = selectedPage.id;
    const topic =
      (block.params?.topic as string | undefined) || selectedPage.title || "";
    setSupplementingBlockId(block.id);
    try {
      const { book_revision } = await bookApi.supplement(
        detail.book.id,
        pageId,
        topic,
        expectedRevision,
      );
      applyBookRevision(book_revision);
      await hydratePage(pageId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      notify(t("Could not add extra practice: {{message}}", { message: msg }), {
        tone: "error",
        durationMs: 8000,
      });
    } finally {
      setSupplementingBlockId(null);
    }
  };

  const refreshCapturesSorted = useCallback((captures: LearningCapture[]) => {
    return [...captures].sort((a, b) => b.updated_at - a.updated_at);
  }, []);

  const applyCapturePatch = useCallback(
    (capture: LearningCapture) => {
      setLearningCaptures((current) =>
        refreshCapturesSorted(
          current.some((item) => item.id === capture.id)
            ? current.map((item) => (item.id === capture.id ? capture : item))
            : [capture, ...current],
        ),
      );
    },
    [refreshCapturesSorted],
  );

  const handleCaptureSelection = async (payload: {
    page_id: string;
    block_id: string;
    source_text: string;
    context_before?: string;
    context_after?: string;
    source_locator?: string;
  }) => {
    if (!detail) return;
    const result = await bookApi.createLearningCapture(detail.book.id, {
      ...payload,
      book_title: detail.book.title,
      chapter_title: selectedPage?.title || "",
    });
    applyCapturePatch(result.capture);
  };

  const handleApproveCapture = async (capture: LearningCapture) => {
    if (!detail) return;
    const result = await bookApi.updateLearningCapture(
      detail.book.id,
      capture.id,
      { status: "approved" },
    );
    applyCapturePatch(result.capture);
    notify(t("Capture approved"), {
      tone: "success",
      durationMs: 3000,
    });
  };

  const handleRejectCapture = async (capture: LearningCapture) => {
    if (!detail) return;
    const result = await bookApi.updateLearningCapture(
      detail.book.id,
      capture.id,
      { status: "rejected" },
    );
    applyCapturePatch(result.capture);
    notify(t("Capture rejected"), {
      tone: "info",
      durationMs: 3000,
    });
  };

  const handlePageChatSession = async (sessionId: string) =>
    guard("Link chat session", async () => {
      if (!detail || !selectedPage || !sessionId) return;
      const existing =
        detail.book.metadata?.page_chat_sessions?.[selectedPage.id];
      if (existing === sessionId) return;
      const result = await bookApi.setPageChatSession(
        detail.book.id,
        selectedPage.id,
        sessionId,
      );
      setDetail((current) =>
        current && current.book.id === result.book.id
          ? { ...current, book: result.book }
          : current,
      );
    });

  // ── Render ─────────────────────────────────────────────────────────

  return (
    <div className="flex h-full w-full">
      {view !== "list" && (
        <BookSidebar
          book={detail?.book || pendingBook || null}
          onBackToLibrary={() => void handleSelectBook(null)}
          pages={detail?.pages || []}
          selectedPageId={selectedPageId}
          onSelectPage={handleSelectPage}
          onRebuild={
            detail && canEditBook ? () => void handleRebuildBook() : undefined
          }
          rebuilding={rebuildingBook}
          visitedPageIds={detail?.progress.visited_page_ids}
          bookmarkedPageIds={detail?.progress.bookmarked_page_ids}
        />
      )}

      <main className="relative flex flex-1 overflow-hidden bg-[var(--background)]">
        {/* Persistent mini progress chip — floats top-right of the workspace
            across creator/spine/reader views as long as generation activity
            exists and isn't fully complete. */}
        {progressHasActivity(progress) && !progressIsComplete(progress) && (
          <div className="pointer-events-none absolute right-3 top-3 z-30">
            <BookProgressTimeline progress={progress} mini />
          </div>
        )}
        <div className="flex-1 overflow-hidden">
          {view === "list" && (
            <BookLibrary
              books={books}
              loading={loadingBooks}
              canCreate={canCreateBook}
              onNewBook={handleNewBook}
              onSelectBook={(id) => void handleSelectBook(id)}
              onDeleteBook={(id) => void handleDeleteBook(id)}
            />
          )}

          {view === "creator" && (
            <div className="h-full overflow-y-auto [scrollbar-gutter:stable]">
              {(confirmingProposal || progressHasActivity(progress)) && (
                <div className="mx-auto mt-4 max-w-4xl px-4">
                  <BookProgressTimeline progress={progress} />
                </div>
              )}
              <BookCreator
                book={pendingBook}
                onCreate={handleCreate}
                loading={creating}
                proposal={pendingProposal}
                onConfirmProposal={handleConfirmProposal}
                confirmLoading={confirmingProposal}
              />
            </div>
          )}

          {view === "spine" && detail?.spine && (
            <div className="flex h-full flex-col overflow-hidden">
              <div className="flex-1 overflow-hidden">
                <SpineEditor
                  key={`${detail.spine.book_id}:${detail.spine.version}`}
                  spine={detail.spine}
                  onConfirm={handleConfirmSpine}
                  loading={confirmingSpine}
                  depth={detail.book.depth}
                />
              </div>
            </div>
          )}

          {view === "reader" && (
            // Column layout so banners push the reader down instead of
            // overflowing it — `PageReader` fills whatever height is left.
            <div className="flex h-full flex-col overflow-hidden">
              <BookPausedBanner
                book={detail?.book || null}
                onResume={
                  canEditBook ? () => void handleResumeBook() : undefined
                }
                resuming={resumingBook}
              />
              <BookHealthBanner
                bookId={selectedBookId}
                refreshKey={detail?.book.updated_at}
                expectedRevision={expectedRevision}
                onRevisionChange={applyBookRevision}
                explorationFailed={!!detail?.book.metadata?.exploration_failed}
                onRecompile={
                  canEditBook
                    ? (pageId) => {
                        setSelectedPageId(pageId);
                        void compilePage(pageId, true);
                      }
                    : undefined
                }
              />
              {detail?.book.source === "shared" && (
                <div className="mx-6 mt-3 rounded-lg border border-sky-300/60 bg-sky-50 px-3 py-2 text-xs text-sky-900 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100">
                  {canEditBook
                    ? t(
                        "Shared book: content edits affect everyone who can access it. Reading progress and captures remain private to you.",
                      )
                    : t(
                        "Shared book (read only): your reading progress, bookmarks and captures remain private to you.",
                      )}
                </div>
              )}
              {/* The reader owns the height that is left; the capture inbox
                  sits under it at its natural height. Both need this to be a
                  flex column — a plain block here collapses `PageReader`'s
                  `h-full` to auto, which stops the body scrolling and pushes
                  the page-turn footer out of view. */}
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                <div className="min-h-0 flex-1 overflow-hidden">
                  <PageReader
                    page={selectedPage}
                    bookId={detail?.book.id}
                    bookLanguage={detail?.book.language}
                    loading={
                      !!compilingPageId && compilingPageId === selectedPage?.id
                    }
                    onRegenerateBlock={
                      canEditBook
                        ? (block) => void handleRegenerateBlock(block)
                        : undefined
                    }
                    onDeleteBlock={
                      canEditBook
                        ? (block) => void handleDeleteBlock(block)
                        : undefined
                    }
                    onMoveBlock={(block, dir) =>
                      canEditBook ? void handleMoveBlock(block, dir) : undefined
                    }
                    onChangeBlockType={(block, t) =>
                      canEditBook
                        ? void handleChangeBlockType(block, t)
                        : undefined
                    }
                    onInsertBlock={
                      canEditBook ? (t) => handleInsertBlock(t) : undefined
                    }
                    onDeepDive={(topic, blockId) =>
                      canEditBook ? handleDeepDive(topic, blockId) : undefined
                    }
                    onOpenPage={(pageId) => handleSelectPage(pageId)}
                    onQuizAttempt={(block, args) =>
                      void handleQuizAttempt(block, args)
                    }
                    onRequestSupplement={
                      canEditBook
                        ? (block) => void handleRequestSupplement(block)
                        : undefined
                    }
                    supplementingBlockId={supplementingBlockId}
                    onUpdateBody={canEditBook ? handleUpdateBody : undefined}
                    attempts={detail?.progress.quiz_attempts}
                    previousPage={pageNeighbours.previous}
                    nextPage={pageNeighbours.next}
                    onNavigate={handleSelectPage}
                    bookmarked={
                      !!selectedPage &&
                      !!detail?.progress.bookmarked_page_ids.includes(
                        selectedPage.id,
                      )
                    }
                    onToggleBookmark={() => void handleToggleBookmark()}
                    pendingDeepDiveTopic={pendingDeepDiveTopic}
                    onRecompile={
                      canEditBook && selectedPage
                        ? () => void compilePage(selectedPage.id, true)
                        : undefined
                    }
                    onCaptureSelection={(payload) =>
                      void guard("Save selection", () =>
                        handleCaptureSelection(payload),
                      )
                    }
                  />
                </div>
                <div className="shrink-0 border-t border-[var(--border)] px-8 py-3">
                  <LearningCapturePanel
                    captures={learningCaptures}
                    loading={loadingLearningCaptures}
                    onApprove={(capture) =>
                      void guard("Approve capture", () =>
                        handleApproveCapture(capture),
                      )
                    }
                    onReject={(capture) =>
                      void guard("Reject capture", () =>
                        handleRejectCapture(capture),
                      )
                    }
                  />
                </div>
              </div>
            </div>
          )}

          {view === "spine" && !detail?.spine && (
            <div className="flex h-full items-center justify-center text-[var(--muted-foreground)]">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />{" "}
              {t("Loading spine…")}
            </div>
          )}
        </div>

        {view === "reader" && !chatOpen && (
          <button
            onClick={() => setChatOpen(true)}
            className="absolute bottom-4 right-4 inline-flex items-center gap-2 rounded-full bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] shadow-lg hover:opacity-90"
          >
            <MessageSquare className="h-4 w-4" />
            {t("Chat")}
          </button>
        )}

        {view === "reader" && chatOpen && (
          <BookChatPanel
            book={detail?.book || null}
            page={selectedPage}
            open={chatOpen}
            onClose={() => setChatOpen(false)}
            initialSessionId={selectedPageChatSessionId}
            onSessionResolved={(sessionId) =>
              void handlePageChatSession(sessionId)
            }
          />
        )}
      </main>
    </div>
  );
}
