"use client";

import { useEffect, useRef, useState } from "react";
import {
  Loader2,
  RefreshCcw,
  Plus,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import type { Block, BlockType, Page } from "@/lib/book-types";
import BlockRenderer from "./blocks/BlockRenderer";
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
  onQuizAttempt?: (
    block: Block,
    args: { questionId?: string; userAnswer?: string; isCorrect: boolean },
  ) => void;
  onRecompile?: () => void;
  pendingDeepDiveTopic?: string | null;
  loading?: boolean;
  bookId?: string;
  bookLanguage?: string;
}

export default function PageReader({
  page,
  onRegenerateBlock,
  onDeleteBlock,
  onMoveBlock,
  onChangeBlockType,
  onInsertBlock,
  onDeepDive,
  onQuizAttempt,
  onRecompile,
  pendingDeepDiveTopic,
  loading = false,
  bookId,
  bookLanguage,
}: PageReaderProps) {
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

  if (!page) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--muted-foreground)]">
        Select a chapter to start reading.
      </div>
    );
  }

  const isZh = (bookLanguage || "").toLowerCase().startsWith("zh");
  const expandTip = isZh ? "展开标题栏" : "Expand header";
  const collapseTip = isZh ? "折叠标题栏" : "Collapse header";

  return (
    // The outer container is `relative` so the floating outline nav can
    // anchor to the viewport-stable column instead of being trapped inside
    // the scrollable inner div.
    <div className="relative flex h-full flex-col">
      <header
        className={[
          "border-b border-[var(--border)] bg-[var(--card)]/60 backdrop-blur transition-all duration-200 ease-out",
          headerCollapsed ? "px-4 py-2 sm:px-8" : "px-4 py-4 sm:px-8 sm:py-5",
        ].join(" ")}
      >
        <div className="mx-auto flex w-full max-w-[78ch] items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <h1
              className={[
                "font-semibold leading-tight tracking-tight text-[var(--foreground)] transition-all duration-200",
                headerCollapsed ? "truncate text-[15px]" : "text-[22px] sm:text-[26px]",
              ].join(" ")}
              title={page.title || "Untitled chapter"}
            >
              {page.title || "Untitled chapter"}
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
                {page.status}
              </span>
            )}
            {!headerCollapsed && onRecompile && (
              <button
                onClick={onRecompile}
                className="hidden items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-xs font-medium text-[var(--muted-foreground)] hover:border-[var(--primary)]/40 hover:text-[var(--primary)] sm:inline-flex"
              >
                <RefreshCcw className="h-3.5 w-3.5" /> Recompile
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
        className="flex-1 overflow-y-auto px-4 py-5 sm:px-8 sm:py-8"
      >
        {loading && page.blocks.length === 0 ? (
          <div className="mx-auto flex w-full max-w-[78ch] items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Loader2 className="h-4 w-4 animate-spin" />
            Compiling page…
          </div>
        ) : (
          <article className="mx-auto flex w-full max-w-[78ch] flex-col gap-6 [&>:first-child]:mt-0">
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
                  onQuizAttempt={onQuizAttempt}
                  pendingDeepDiveTopic={pendingDeepDiveTopic}
                  bookId={bookId}
                  currentPageId={page.id}
                  bookLanguage={bookLanguage}
                />
              </div>
            ))}
            {page.blocks.length === 0 && (
              <div className="text-sm text-[var(--muted-foreground)]">
                This page has no blocks yet.
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
                  Insert block
                </button>
                {showInsertMenu && (
                  <div className="absolute top-full z-10 mt-1 grid w-[min(18rem,calc(100vw-2rem))] grid-cols-2 gap-1 rounded-lg border border-[var(--border)] bg-[var(--card)] p-2 shadow-lg">
                    {INSERTABLE_TYPES.map((t) => (
                      <button
                        key={t}
                        onClick={async () => {
                          setShowInsertMenu(false);
                          setInserting(true);
                          try {
                            await onInsertBlock(t);
                          } finally {
                            setInserting(false);
                          }
                        }}
                        className="rounded px-2 py-1 text-left text-xs text-[var(--foreground)] hover:bg-[var(--background)]"
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </article>
        )}
      </div>

      {/* Floating outline lives outside the scroll container so it stays
          pinned to the viewport regardless of page scrolling. */}
      <PageOutlineNav
        blocks={page.blocks}
        scrollContainer={scrollContainer}
        language={bookLanguage}
        resetKey={page.id}
      />
    </div>
  );
}
