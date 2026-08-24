"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bookmark,
  BookmarkCheck,
  Loader2,
  Pencil,
  RefreshCcw,
  Plus,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Block, BlockType, Page, QuizAttempt } from "@/lib/book-types";
import BlockRenderer from "./blocks/BlockRenderer";
import type { QuizAttemptArgs } from "./blocks/QuizBlock";
import PageOutlineNav from "./PageOutlineNav";

const INSERTABLE_TYPES: BlockType[] = [
  "text",
  "callout",
  "quiz",
  "code",
  "timeline",
  "flash_cards",
  "figure",
  "interactive",
  "animation",
  "deep_dive",
  "user_note",
];

export interface PageReaderProps {
  page: Page | null;
  onRegenerateBlock?: (block: Block) => void;
  onDeleteBlock?: (block: Block) => void;
  onMoveBlock?: (block: Block, direction: "up" | "down") => void;
  onChangeBlockType?: (block: Block, newType: BlockType) => void;
  onInsertBlock?: (block_type: BlockType) => Promise<void> | void;
  onDeepDive?: (topic: string, blockId: string) => Promise<void> | void;
  onOpenPage?: (pageId: string) => void;
  onQuizAttempt?: (block: Block, args: QuizAttemptArgs) => void;
  /** Reader asked for extra practice on a quiz they got wrong. */
  onRequestSupplement?: (block: Block) => void;
  supplementingBlockId?: string | null;
  onUpdateBody?: (block: Block, body: string) => Promise<void> | void;
  /** Previous quiz answers, so they survive leaving and returning. */
  attempts?: QuizAttempt[];
  onRecompile?: () => void;
  pendingDeepDiveTopic?: string | null;
  loading?: boolean;
  bookId?: string;
  bookLanguage?: string;
  // ── Chapter navigation ──
  previousPage?: Page | null;
  nextPage?: Page | null;
  onNavigate?: (pageId: string) => void;
  bookmarked?: boolean;
  onToggleBookmark?: () => void;

  onCaptureSelection?: (payload: {
    page_id: string;
    block_id: string;
    source_text: string;
    context_before?: string;
    context_after?: string;
    source_locator?: string;
  }) => Promise<void> | void;
}

export default function PageReader({
  page,
  onRegenerateBlock,
  onDeleteBlock,
  onMoveBlock,
  onChangeBlockType,
  onInsertBlock,
  onDeepDive,
  onOpenPage,
  onQuizAttempt,
  onRequestSupplement,
  supplementingBlockId,
  onUpdateBody,
  attempts,
  onRecompile,
  pendingDeepDiveTopic,
  loading = false,
  bookId,
  bookLanguage,
  previousPage,
  nextPage,
  onNavigate,
  bookmarked = false,
  onToggleBookmark,
  onCaptureSelection,
}: PageReaderProps) {
  const { t } = useTranslation();
  const [showInsertMenu, setShowInsertMenu] = useState(false);
  const [inserting, setInserting] = useState(false);
  const [scrollContainer, setScrollContainer] = useState<HTMLDivElement | null>(
    null,
  );

  // ── Collapsible header ──────────────────────────────────────────────
  // Default expanded; collapse on user-initiated scroll-down past threshold;
  // re-expand when user returns to the very top. Manual toggle via button.
  const [headerCollapsed, setHeaderCollapsed] = useState(false);
  const [userToggled, setUserToggled] = useState(false);
  const lastScrollTopRef = useRef(0);

  // Reset header + scroll bookkeeping whenever we load a new page.
  useEffect(() => {
    setHeaderCollapsed(false);
    setUserToggled(false);
    lastScrollTopRef.current = 0;
  }, [page?.id]);

  useEffect(() => {
    if (!scrollContainer) return;
    const handler = () => {
      const top = scrollContainer.scrollTop;
      const last = lastScrollTopRef.current;
      lastScrollTopRef.current = top;
      // Snap back to expanded when user scrolls all the way to the top,
      // even if they previously toggled manually.
      if (top <= 8) {
        setHeaderCollapsed(false);
        setUserToggled(false);
        return;
      }
      if (userToggled) return;
      // Collapse on downward scroll past a small threshold.
      if (top > last && top > 80) {
        setHeaderCollapsed(true);
      }
    };
    scrollContainer.addEventListener("scroll", handler, { passive: true });
    return () => scrollContainer.removeEventListener("scroll", handler);
  }, [scrollContainer, userToggled]);

  const normalizeText = useCallback((value: string): string => {
    return (value || "").replace(/\s+/g, " ").trim();
  }, []);

  const captureSelection = useCallback(() => {
    if (!onCaptureSelection || !page) {
      return;
    }
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) {
      window.alert(t("Please select some text before saving."));
      return;
    }

    const sourceText = normalizeText(selection.toString());
    if (!sourceText) {
      window.alert(t("Selected text is empty."));
      return;
    }

    const anchor = selection.anchorNode;
    const anchorEl =
      anchor && anchor.nodeType === Node.TEXT_NODE
        ? anchor.parentElement
        : (anchor as HTMLElement | null);
    const blockEl = anchorEl?.closest?.(
      "[data-block-id]",
    ) as HTMLElement | null;
    const blockId = blockEl?.getAttribute("data-block-id") || "";

    const rawContext = blockEl?.textContent || selection.toString();
    const contextText = rawContext || "";
    const normalizedContext = normalizeText(contextText);
    const sourceStart = normalizedContext.indexOf(sourceText);
    const sourceEnd = sourceStart >= 0 ? sourceStart + sourceText.length : -1;
    const beforeStart = sourceStart >= 0 ? Math.max(0, sourceStart - 120) : 0;
    const afterEnd =
      sourceEnd >= 0 ? Math.min(normalizedContext.length, sourceEnd + 120) : 0;
    const contextBefore =
      sourceStart >= 0 ? normalizedContext.slice(beforeStart, sourceStart) : "";
    const contextAfter =
      sourceEnd >= 0 ? normalizedContext.slice(sourceEnd, afterEnd) : "";

    const sourceLocator = blockId
      ? `/book/${page.book_id}/pages/${page.id}/blocks/${blockId}`
      : `/book/${page.book_id}/pages/${page.id}`;

    void onCaptureSelection({
      page_id: page.id,
      block_id: blockId,
      source_text: sourceText,
      context_before: contextBefore,
      context_after: contextAfter,
      source_locator: sourceLocator,
    });
    selection.removeAllRanges();
  }, [onCaptureSelection, normalizeText, page, t]);

  useEffect(() => {
    if (!onNavigate) return;
    const handler = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      // Never steal arrow keys from a field the reader is typing in.
      if (
        target &&
        (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      ) {
        return;
      }
      if (event.key === "ArrowLeft" && previousPage) {
        onNavigate(previousPage.id);
      } else if (event.key === "ArrowRight" && nextPage) {
        onNavigate(nextPage.id);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onNavigate, previousPage, nextPage]);

  if (!page) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--muted-foreground)]">
        {t("Select a chapter to start reading.")}
      </div>
    );
  }

  const expandTip = t("Expand header");
  const collapseTip = t("Collapse header");
  const failedBlocks = page.blocks.filter((block) => block.status === "error");
  const hasFailedBlocks = failedBlocks.length > 0;
  const canCaptureSelection =
    !!onCaptureSelection && !loading && page.blocks.length > 0;

  return (
    // The outer container is `relative` so the floating outline nav can
    // anchor to the viewport-stable column instead of being trapped inside
    // the scrollable inner div.
    <div className="relative flex h-full flex-col">
      <header
        className={[
          "border-b border-[var(--border)] bg-[var(--card)]/60 backdrop-blur transition-all duration-200 ease-out",
          headerCollapsed ? "px-8 py-2" : "px-8 py-5",
        ].join(" ")}
      >
        <div className="mx-auto flex w-full max-w-[78ch] items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h1
              className={[
                "font-semibold leading-tight tracking-tight text-[var(--foreground)] transition-all duration-200",
                headerCollapsed ? "truncate text-[15px]" : "text-[26px]",
              ].join(" ")}
              title={page.title || t("Untitled chapter")}
            >
              {page.title || t("Untitled chapter")}
            </h1>
            {!headerCollapsed && page.learning_objectives.length > 0 && (
              <ul className="mt-3 space-y-0.5 text-[12.5px] text-[var(--muted-foreground)]">
                {page.learning_objectives.map((obj, idx) => (
                  <li key={idx}>• {obj}</li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {!headerCollapsed && (
              <span className="rounded-full bg-[var(--muted)] px-2.5 py-0.5 text-[11px] uppercase tracking-wider text-[var(--muted-foreground)]">
                {t(page.status)}
              </span>
            )}
            {onToggleBookmark && (
              <button
                type="button"
                onClick={onToggleBookmark}
                title={
                  bookmarked ? t("Remove bookmark") : t("Bookmark this chapter")
                }
                aria-pressed={bookmarked}
                className={`inline-flex h-6 w-6 items-center justify-center rounded-md transition-colors ${
                  bookmarked
                    ? "text-[var(--primary)]"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)]"
                }`}
              >
                {bookmarked ? (
                  <BookmarkCheck className="h-3.5 w-3.5" />
                ) : (
                  <Bookmark className="h-3.5 w-3.5" />
                )}
              </button>
            )}
            {!headerCollapsed && onRecompile && (
              <button
                onClick={onRecompile}
                disabled={loading}
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-xs font-medium text-[var(--muted-foreground)] hover:border-[var(--primary)]/40 hover:text-[var(--primary)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCcw className="h-3.5 w-3.5" />
                )}
                {loading ? t("Regenerating…") : t("Force regenerate")}
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                setHeaderCollapsed((v) => !v);
                setUserToggled(true);
              }}
              title={headerCollapsed ? expandTip : collapseTip}
              aria-label={headerCollapsed ? expandTip : collapseTip}
              className="inline-flex h-6 w-6 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)]"
            >
              {headerCollapsed ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronUp className="h-3.5 w-3.5" />
              )}
            </button>
          </div>
        </div>
      </header>

      <div
        ref={setScrollContainer}
        className="flex-1 overflow-y-auto px-8 py-8"
      >
        {loading && page.blocks.length === 0 ? (
          <div className="mx-auto flex w-full max-w-[78ch] items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("Compiling page…")}
          </div>
        ) : (
          <article className="mx-auto flex w-full max-w-[78ch] flex-col gap-6 [&>:first-child]:mt-0">
            {hasFailedBlocks && (
              <div className="rounded-2xl border border-amber-300/70 bg-amber-50 px-4 py-3 text-sm text-amber-950 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-100">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div className="font-semibold">
                    {failedBlocks.length === 1
                      ? t("{{count}} block failed", {
                          count: failedBlocks.length,
                        })
                      : t("{{count}} blocks failed", {
                          count: failedBlocks.length,
                        })}
                  </div>
                  {onRecompile && (
                    <button
                      onClick={onRecompile}
                      disabled={loading}
                      className="inline-flex items-center gap-1 rounded-md border border-current px-2 py-1 text-xs font-medium hover:bg-white/40 dark:hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {loading ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <RefreshCcw className="h-3.5 w-3.5" />
                      )}
                      {loading ? t("Regenerating…") : t("Regenerate page")}
                    </button>
                  )}
                </div>
                <div className="space-y-1.5 text-xs opacity-90">
                  {failedBlocks.slice(0, 5).map((block) => {
                    const failure = block.metadata?.failure as
                      | { kind?: string; message?: string }
                      | undefined;
                    return (
                      <div
                        key={block.id}
                        className="flex flex-wrap items-center gap-2"
                      >
                        <code className="rounded bg-white/50 px-1.5 py-0.5 dark:bg-white/10">
                          {block.type}
                        </code>
                        <span>
                          {failure?.kind || t("error")}:{" "}
                          {block.error ||
                            failure?.message ||
                            t("Unknown error")}
                        </span>
                        {onRegenerateBlock && (
                          <button
                            onClick={() => onRegenerateBlock(block)}
                            className="rounded border border-current px-1.5 py-0.5 text-[11px] font-medium hover:bg-white/40 dark:hover:bg-white/10"
                          >
                            {t("Retry block")}
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            {page.blocks.map((block) => (
              <div
                key={block.id}
                id={`block-${block.id}`}
                className="scroll-mt-6"
              >
                <BlockRenderer
                  block={block}
                  onRegenerate={onRegenerateBlock}
                  onDelete={onDeleteBlock}
                  onMove={onMoveBlock}
                  onChangeType={onChangeBlockType}
                  onDeepDive={onDeepDive}
                  onOpenPage={onOpenPage}
                  onQuizAttempt={onQuizAttempt}
                  onRequestSupplement={onRequestSupplement}
                  supplementing={supplementingBlockId === block.id}
                  onUpdateBody={onUpdateBody}
                  attempts={attempts}
                  pendingDeepDiveTopic={pendingDeepDiveTopic}
                  bookId={bookId}
                  currentPageId={page.id}
                  bookLanguage={bookLanguage}
                />
              </div>
            ))}
            {page.blocks.length === 0 && (
              <div className="text-sm text-[var(--muted-foreground)]">
                {t("This page has no blocks yet.")}
              </div>
            )}

            {onInsertBlock && (
              <div className="relative mt-2 flex justify-center">
                <button
                  onClick={() => setShowInsertMenu((v) => !v)}
                  disabled={inserting}
                  className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-xs font-medium text-[var(--muted-foreground)] hover:border-[var(--primary)]/50 hover:text-[var(--primary)] disabled:opacity-60"
                >
                  {inserting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Plus className="h-3.5 w-3.5" />
                  )}
                  {t("Insert block")}
                </button>
                {showInsertMenu && (
                  <div className="absolute top-full mt-1 z-10 grid w-72 grid-cols-2 gap-1 rounded-lg border border-[var(--border)] bg-[var(--card)] p-2 shadow-lg">
                    {INSERTABLE_TYPES.map((blockType) => (
                      <button
                        key={blockType}
                        onClick={async () => {
                          setShowInsertMenu(false);
                          setInserting(true);
                          try {
                            await onInsertBlock(blockType);
                          } finally {
                            setInserting(false);
                          }
                        }}
                        className="rounded px-2 py-1 text-left text-xs text-[var(--foreground)] hover:bg-[var(--background)]"
                      >
                        {t(blockType)}
                      </button>
                    ))}
                  </div>
                )}
                {canCaptureSelection && (
                  <button
                    type="button"
                    onClick={captureSelection}
                    className="inline-flex items-center justify-center rounded-full border border-dashed border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-xs font-medium text-[var(--muted-foreground)] hover:border-[var(--primary)]/50 hover:text-[var(--primary)]"
                  >
                    <Pencil className="mr-1.5 h-3.5 w-3.5" />
                    {t("Save selection")}
                  </button>
                )}
              </div>
            )}
          </article>
        )}
      </div>

      {(previousPage || nextPage) && onNavigate && (
        <footer className="border-t border-[var(--border)] bg-[var(--card)]/60 px-8 py-2.5">
          <div className="mx-auto flex w-full max-w-[78ch] items-center justify-between gap-3">
            <NavButton
              page={previousPage}
              direction="previous"
              label={t("Previous chapter")}
              onNavigate={onNavigate}
            />
            <span className="shrink-0 text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]/70">
              {t("← / → to turn pages")}
            </span>
            <NavButton
              page={nextPage}
              direction="next"
              label={t("Next chapter")}
              onNavigate={onNavigate}
            />
          </div>
        </footer>
      )}

      {/* Floating outline lives outside the scroll container so it stays
          pinned to the viewport regardless of page scrolling. */}
      <PageOutlineNav
        key={page.id}
        blocks={page.blocks}
        scrollContainer={scrollContainer}
        language={bookLanguage}
      />
    </div>
  );
}

function NavButton({
  page,
  direction,
  label,
  onNavigate,
}: {
  page: Page | null | undefined;
  direction: "previous" | "next";
  label: string;
  onNavigate: (pageId: string) => void;
}) {
  if (!page) return <span className="min-w-0 flex-1" />;
  const isNext = direction === "next";
  return (
    <button
      type="button"
      onClick={() => onNavigate(page.id)}
      className={`group inline-flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-2 py-1 text-xs text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)] ${
        isNext ? "justify-end text-right" : "justify-start text-left"
      }`}
      title={page.title}
    >
      {!isNext && <ChevronLeft className="h-3.5 w-3.5 shrink-0" />}
      <span className="min-w-0">
        <span className="block text-[10px] uppercase tracking-wider opacity-70">
          {label}
        </span>
        <span className="block truncate">{page.title}</span>
      </span>
      {isNext && <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
    </button>
  );
}
