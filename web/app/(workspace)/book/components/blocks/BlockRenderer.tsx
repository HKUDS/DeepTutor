"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  Pencil,
  RefreshCw,
  Trash2,
  ArrowUp,
  ArrowDown,
  Replace,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Block, BlockType, QuizAttempt } from "@/lib/book-types";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";

import BlockBodyEditor from "./BlockBodyEditor";
import TextBlock from "./TextBlock";
import CalloutBlock from "./CalloutBlock";
import QuizBlock, { type QuizAttemptArgs } from "./QuizBlock";
import UserNoteBlock from "./UserNoteBlock";
import FigureBlock from "./FigureBlock";
import InteractiveBlock from "./InteractiveBlock";
import AnimationBlock from "./AnimationBlock";
import CodeBlock from "./CodeBlock";
import TimelineBlock from "./TimelineBlock";
import FlashCardsBlock from "./FlashCardsBlock";
import DeepDiveBlock from "./DeepDiveBlock";
import ConceptGraphBlock from "./ConceptGraphBlock";
import SectionBlock from "./SectionBlock";
import PlaceholderBlock from "./PlaceholderBlock";

// How long a destructive control stays armed before it forgets.
const CONFIRM_WINDOW_MS = 3500;

// Blocks that are a single run of prose, so a plain text box can edit them
// without destroying structure the renderer depends on. Mirrors
// `_EDITABLE_BLOCK_TYPES` on the backend.
const EDITABLE_BODY_TYPES: BlockType[] = ["text", "callout"];

/** Where a block keeps its prose — `text` blocks use both keys, historically. */
function bodyKeyFor(block: Block): "body" | "content" {
  return block.type === "text" && "content" in (block.payload || {})
    ? "content"
    : "body";
}

const CHANGEABLE_TYPES: BlockType[] = [
  "text",
  "section",
  "callout",
  "quiz",
  "code",
  "timeline",
  "flash_cards",
  "figure",
  "interactive",
  "animation",
  "deep_dive",
];

export interface BlockRendererProps {
  block: Block;
  onRegenerate?: (block: Block) => void;
  onDelete?: (block: Block) => void;
  onMove?: (block: Block, direction: "up" | "down") => void;
  onChangeType?: (block: Block, newType: BlockType) => void;
  onDeepDive?: (topic: string, blockId: string) => Promise<void> | void;
  onOpenPage?: (pageId: string) => void;
  onQuizAttempt?: (block: Block, args: QuizAttemptArgs) => void;
  onRequestSupplement?: (block: Block) => void;
  supplementing?: boolean;
  /** Previous quiz answers, passed through to `QuizBlock`. */
  attempts?: QuizAttempt[];
  /** Save edited prose. Omit to render the block read-only. */
  onUpdateBody?: (block: Block, body: string) => Promise<void> | void;
  pendingDeepDiveTopic?: string | null;
  bookId?: string;
  currentPageId?: string;
  bookLanguage?: string;
}

export default function BlockRenderer({
  block,
  onRegenerate,
  onDelete,
  onMove,
  onChangeType,
  onDeepDive,
  onOpenPage,
  onQuizAttempt,
  onRequestSupplement,
  supplementing = false,
  attempts,
  onUpdateBody,
  pendingDeepDiveTopic,
  bookId,
  currentPageId,
  bookLanguage,
}: BlockRendererProps) {
  const { t } = useTranslation();
  const [showTypeMenu, setShowTypeMenu] = useState(false);
  const [editingBody, setEditingBody] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // The delete control lives in a toolbar that only exists while the pointer is
  // over the block. Auto-disarm so an armed state can never outlive the
  // interaction that created it and surprise the next click.
  useEffect(() => {
    if (!confirmDelete) return;
    const timer = setTimeout(() => setConfirmDelete(false), CONFIRM_WINDOW_MS);
    return () => clearTimeout(timer);
  }, [confirmDelete]);

  if (block.status === "pending" || block.status === "generating") {
    return (
      <div className="flex items-center gap-2 rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm text-[var(--muted-foreground)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>{t("Generating {{type}}…", { type: t(block.type) })}</span>
      </div>
    );
  }
  if (block.status === "error") {
    const failure = block.metadata?.failure as
      | { kind?: string; message?: string; retryable?: boolean }
      | undefined;
    return (
      <div className="rounded-2xl border border-rose-300/60 bg-rose-50 px-4 py-3 text-sm text-rose-900 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-100">
        <div className="mb-1 flex items-center gap-2 font-medium">
          <AlertTriangle className="h-4 w-4" />
          {t("{{type}} block failed", { type: t(block.type) })}
        </div>
        {failure?.kind && (
          <div className="mb-1 text-[11px] uppercase tracking-wider opacity-70">
            {failure.kind}
            {failure.retryable === false ? ` · ${t("not retryable")}` : ""}
          </div>
        )}
        <div className="text-xs opacity-80">
          {block.error || failure?.message || t("Unknown error")}
        </div>
        {onRegenerate && (
          <button
            onClick={() => onRegenerate(block)}
            className="mt-2 inline-flex rounded-md border border-rose-400/60 bg-white/40 px-2 py-1 text-xs font-medium hover:bg-white/60 dark:bg-white/10"
          >
            {t("Retry")}
          </button>
        )}
      </div>
    );
  }

  let body: React.ReactNode;
  switch (block.type) {
    case "text":
      body = <TextBlock block={block} />;
      break;
    case "section":
      body = <SectionBlock block={block} />;
      break;
    case "callout":
      body = <CalloutBlock block={block} />;
      break;
    case "quiz":
      body = (
        <QuizBlock
          block={block}
          onAttempt={onQuizAttempt}
          attempts={attempts}
          onRequestSupplement={
            onRequestSupplement ? () => onRequestSupplement(block) : undefined
          }
          supplementing={supplementing}
        />
      );
      break;
    case "user_note":
      body = (
        <UserNoteBlock
          block={block}
          onSave={
            onUpdateBody ? (value) => onUpdateBody(block, value) : undefined
          }
          // A note the reader just inserted is empty by definition — drop
          // them straight into it rather than making them find the pencil.
          autoEdit={!String(block.payload?.body || "").trim()}
        />
      );
      break;
    case "figure":
      body = <FigureBlock block={block} />;
      break;
    case "interactive":
      body = <InteractiveBlock block={block} />;
      break;
    case "animation":
      body = <AnimationBlock block={block} />;
      break;
    case "code":
      body = <CodeBlock block={block} />;
      break;
    case "timeline":
      body = <TimelineBlock block={block} />;
      break;
    case "flash_cards":
      body = <FlashCardsBlock block={block} />;
      break;
    case "deep_dive":
      body = (
        <DeepDiveBlock
          block={block}
          onDeepDive={onDeepDive}
          onOpenPage={onOpenPage}
          pendingTopic={pendingDeepDiveTopic}
        />
      );
      break;
    case "concept_graph":
      body = (
        <ConceptGraphBlock
          block={block}
          bookId={bookId}
          currentPageId={currentPageId}
          language={bookLanguage}
        />
      );
      break;
    default:
      body = <PlaceholderBlock block={block} />;
  }

  const canEditBody =
    !!onUpdateBody && EDITABLE_BODY_TYPES.includes(block.type);
  const currentBody = String(
    (block.payload as Record<string, unknown> | undefined)?.[
      bodyKeyFor(block)
    ] ?? "",
  );

  if (editingBody && onUpdateBody) {
    body = (
      <BlockBodyEditor
        initialValue={currentBody}
        onSave={async (value) => {
          await onUpdateBody(block, value);
          setEditingBody(false);
        }}
        onCancel={() => setEditingBody(false)}
      />
    );
  }

  const hasActions =
    !!onRegenerate || !!onDelete || !!onMove || !!onChangeType || canEditBody;

  const bridgeText = String(
    (block.payload as Record<string, unknown> | undefined)?.bridge_text ?? "",
  ).trim();
  const showBridge = bridgeText.length > 0;

  return (
    <div className="group relative">
      {showBridge && (
        <div className="mb-3 text-[var(--foreground)]">
          <MarkdownRenderer content={bridgeText} variant="prose" />
        </div>
      )}
      {hasActions && (
        <div className="pointer-events-none absolute -top-3 right-2 z-10 flex translate-y-1 items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--card)] px-1 py-0.5 text-[var(--muted-foreground)] opacity-0 shadow-sm transition group-hover:translate-y-0 group-hover:opacity-100">
          {onMove && (
            <>
              <button
                onClick={() => onMove(block, "up")}
                className="pointer-events-auto rounded p-1 hover:bg-[var(--background)] hover:text-[var(--foreground)]"
                title={t("Move up")}
              >
                <ArrowUp className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => onMove(block, "down")}
                className="pointer-events-auto rounded p-1 hover:bg-[var(--background)] hover:text-[var(--foreground)]"
                title={t("Move down")}
              >
                <ArrowDown className="h-3.5 w-3.5" />
              </button>
            </>
          )}
          {onChangeType && (
            <div className="relative pointer-events-auto">
              <button
                onClick={() => setShowTypeMenu((v) => !v)}
                className="rounded p-1 hover:bg-[var(--background)] hover:text-[var(--foreground)]"
                title={t("Change type")}
              >
                <Replace className="h-3.5 w-3.5" />
              </button>
              {showTypeMenu && (
                <div className="absolute right-0 top-full mt-1 max-h-60 w-44 overflow-y-auto rounded-md border border-[var(--border)] bg-[var(--card)] p-1 shadow-lg">
                  {CHANGEABLE_TYPES.filter((type) => type !== block.type).map(
                    (type) => (
                      <button
                        key={type}
                        onClick={() => {
                          setShowTypeMenu(false);
                          onChangeType(block, type);
                        }}
                        className="block w-full rounded px-2 py-1 text-left text-xs hover:bg-[var(--background)] hover:text-[var(--foreground)]"
                      >
                        {t(type)}
                      </button>
                    ),
                  )}
                </div>
              )}
            </div>
          )}
          {canEditBody && !editingBody && (
            <button
              onClick={() => setEditingBody(true)}
              className="pointer-events-auto rounded p-1 hover:bg-[var(--background)] hover:text-[var(--foreground)]"
              title={t("Edit text")}
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
          )}
          {onRegenerate && (
            <button
              onClick={() => onRegenerate(block)}
              className="pointer-events-auto rounded p-1 hover:bg-[var(--background)] hover:text-[var(--foreground)]"
              title={t("Regenerate")}
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          )}
          {onDelete && (
            <button
              onClick={() => {
                if (confirmDelete) {
                  setConfirmDelete(false);
                  onDelete(block);
                } else {
                  setConfirmDelete(true);
                }
              }}
              onBlur={() => setConfirmDelete(false)}
              className={`pointer-events-auto rounded p-1 ${
                confirmDelete
                  ? "bg-rose-500/15 text-rose-600 dark:text-rose-300"
                  : "hover:bg-rose-100 hover:text-rose-700 dark:hover:bg-rose-500/10 dark:hover:text-rose-200"
              }`}
              title={
                confirmDelete
                  ? t("Click again to delete this block")
                  : t("Delete")
              }
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      )}
      {body}
    </div>
  );
}
