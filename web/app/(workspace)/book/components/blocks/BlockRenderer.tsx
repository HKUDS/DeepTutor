"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Loader2,
  RefreshCw,
  Trash2,
  ArrowUp,
  ArrowDown,
  Replace,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Block, BlockType } from "@/lib/book-types";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";

import TextBlock from "./TextBlock";
import CalloutBlock from "./CalloutBlock";
import QuizBlock from "./QuizBlock";
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
  onQuizAttempt?: (
    block: Block,
    args: { questionId?: string; userAnswer?: string; isCorrect: boolean },
  ) => void;
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
  onQuizAttempt,
  pendingDeepDiveTopic,
  bookId,
  currentPageId,
  bookLanguage,
}: BlockRendererProps) {
  const { t } = useTranslation();
  const [showTypeMenu, setShowTypeMenu] = useState(false);

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
      body = <QuizBlock block={block} onAttempt={onQuizAttempt} />;
      break;
    case "user_note":
      body = <UserNoteBlock block={block} />;
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

  const hasActions = !!onRegenerate || !!onDelete || !!onMove || !!onChangeType;

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
              onClick={() => onDelete(block)}
              className="pointer-events-auto rounded p-1 hover:bg-rose-100 hover:text-rose-700 dark:hover:bg-rose-500/10 dark:hover:text-rose-200"
              title={t("Delete")}
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
