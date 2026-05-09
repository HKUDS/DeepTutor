"use client";

import dynamic from "next/dynamic";
import { memo, useCallback, useMemo, useState } from "react";
import {
  BookOpen,
  Brain,
  ClipboardList,
  Coins,
  Copy,
  MessageSquare,
  RefreshCcw,
  Wand2,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SelectedHistorySession } from "@/components/chat/HistorySessionPicker";
import type { SelectedQuestionEntry } from "@/components/chat/QuestionBankPicker";
import AssistantResponse from "@/components/common/AssistantResponse";
import type {
  MessageAttachment,
  MessageRequestSnapshot,
} from "@/context/UnifiedChatContext";
import { apiUrl } from "@/lib/api";
import { docIconFor } from "@/lib/doc-attachments";
import { extractMathAnimatorResult } from "@/lib/math-animator-types";
import { extractQuizQuestions } from "@/lib/quiz-types";
import { extractVisualizeResult } from "@/lib/visualize-types";
import type { StreamEvent } from "@/lib/unified-ws";
import { hasVisibleMarkdownContent } from "@/lib/markdown-display";
import type { SelectedBookReference } from "@/lib/book-references";
import type { SpaceMemoryFile } from "@/lib/space-items";
import { CallTracePanel } from "./TracePanels";

const MathAnimatorViewer = dynamic(
  () => import("@/components/math-animator/MathAnimatorViewer"),
  { ssr: false },
);
const QuizViewer = dynamic(() => import("@/components/quiz/QuizViewer"), {
  ssr: false,
});
const ResearchOutlineEditor = dynamic(
  () => import("@/components/research/ResearchOutlineEditor"),
  { ssr: false },
);
const VisualizationViewer = dynamic(
  () => import("@/components/visualize/VisualizationViewer"),
  { ssr: false },
);

interface ChatMessageItem {
  role: "user" | "assistant" | "system";
  content: string;
  capability?: string;
  events?: StreamEvent[];
  attachments?: MessageAttachment[];
  requestSnapshot?: MessageRequestSnapshot;
}

interface NotebookReferenceGroup {
  notebookId: string;
  notebookName: string;
  count: number;
}

// Returns the i18n key (and a sensible fallback) for the capability badge
// shown above the user's message. Callers must run `t(...)` on the result.
function getModeBadgeLabel(capability?: string | null): string {
  if (!capability || capability === "chat") return "Chat";
  if (capability === "deep_solve") return "Deep Solve";
  if (capability === "deep_question") return "Quiz Generation";
  if (capability === "deep_research") return "Deep Research";
  if (capability === "math_animator") return "Math Animator";
  if (capability === "visualize") return "Visualize";
  return capability;
}

function imageSrcForAttachment(attachment: MessageAttachment): string | null {
  if (attachment.url) {
    if (
      attachment.url.startsWith("http") ||
      attachment.url.startsWith("blob:") ||
      attachment.url.startsWith("data:")
    ) {
      return attachment.url;
    }
    return apiUrl(attachment.url);
  }

  const base64 = attachment.base64?.trim();
  if (!base64) return null;
  if (base64.startsWith("data:")) return base64;
  return `data:${attachment.mime_type || "image/png"};base64,${base64}`;
}

const AssistantMessage = memo(function AssistantMessage({
  msg,
  isStreaming,
  outlineStatus,
  sessionId,
  language,
  onConfirmOutline,
  onAnswerNow,
}: {
  msg: { content: string; capability?: string; events?: StreamEvent[] };
  isStreaming?: boolean;
  outlineStatus?: "editing" | "researching" | "done";
  sessionId?: string | null;
  language?: string;
  onConfirmOutline?: (
    outline: Array<{ title: string; overview: string }>,
    topic: string,
    researchConfig?: Record<string, unknown> | null,
  ) => void;
  onAnswerNow?: () => void;
}) {
  const events = useMemo(() => msg.events ?? [], [msg.events]);
  const hasCallTrace = useMemo(
    () => events.some((event) => Boolean(event.metadata?.call_id)),
    [events],
  );
  const resultEvent = useMemo(
    () => msg.events?.find((event) => event.type === "result") ?? null,
    [msg.events],
  );

  const outlinePreview = useMemo(() => {
    if (msg.capability !== "deep_research" || !resultEvent) return null;
    const meta = resultEvent.metadata as Record<string, unknown> | undefined;
    if (!meta?.outline_preview) return null;
    return {
      sub_topics: (meta.sub_topics ?? []) as Array<{
        title: string;
        overview: string;
      }>,
      topic: String(meta.topic ?? ""),
      research_config: (meta.research_config ?? null) as Record<
        string,
        unknown
      > | null,
    };
  }, [msg.capability, resultEvent]);

  const quizQuestions = useMemo(() => {
    if (msg.capability !== "deep_question" || !resultEvent) return null;
    return extractQuizQuestions(resultEvent.metadata);
  }, [msg.capability, resultEvent]);

  const mathAnimatorResult = useMemo(() => {
    if (msg.capability !== "math_animator" || !resultEvent) return null;
    return extractMathAnimatorResult(resultEvent.metadata);
  }, [msg.capability, resultEvent]);

  const visualizeResult = useMemo(() => {
    if (msg.capability !== "visualize" || !resultEvent) return null;
    return extractVisualizeResult(resultEvent.metadata);
  }, [msg.capability, resultEvent]);

  return (
    <>
      {hasCallTrace ? (
        <CallTracePanel events={events} isStreaming={isStreaming} />
      ) : null}
      {isStreaming && onAnswerNow ? (
        <AnswerNowRow onAnswerNow={onAnswerNow} />
      ) : null}
      {outlinePreview && outlinePreview.sub_topics.length > 0 ? (
        <ResearchOutlineEditor
          outline={outlinePreview.sub_topics}
          topic={outlinePreview.topic}
          onConfirm={(items) =>
            onConfirmOutline?.(
              items,
              outlinePreview.topic,
              outlinePreview.research_config,
            )
          }
          status={outlineStatus}
        />
      ) : mathAnimatorResult ? (
        <MathAnimatorViewer result={mathAnimatorResult} />
      ) : visualizeResult ? (
        <VisualizationViewer result={visualizeResult} />
      ) : quizQuestions && quizQuestions.length > 0 ? (
        <QuizViewer
          questions={quizQuestions}
          sessionId={sessionId}
          language={language}
        />
      ) : (
        <AssistantResponse content={msg.content} />
      )}
    </>
  );
});

AssistantMessage.displayName = "AssistantMessage";

/**
 * Inline "Answer now" affordance shown alongside the active assistant turn.
 * Lives outside the trace panel so it is visible as soon as the turn starts
 * — i.e. even before any tool / reasoning trace has been emitted, which is
 * the common case for the very first user message.
 */
const AnswerNowRow = memo(function AnswerNowRow({
  onAnswerNow,
}: {
  onAnswerNow: () => void;
}) {
  const { t } = useTranslation();
  // Local single-shot guard: once the user has fired "answer now" we lock
  // the button so a second click can't queue a duplicate cancel + restart
  // race against the in-flight synthesis turn. The next assistant turn
  // mounts a fresh ``AnswerNowRow`` with its own state, so this naturally
  // resets per turn without any external bookkeeping.
  const [triggered, setTriggered] = useState(false);
  const handleClick = useCallback(() => {
    if (triggered) return;
    setTriggered(true);
    onAnswerNow();
  }, [triggered, onAnswerNow]);

  return (
    <div className="mt-1.5 mb-3 flex items-center">
      <button
        type="button"
        onClick={handleClick}
        disabled={triggered}
        title={t("Skip reasoning and answer now")}
        aria-disabled={triggered}
        className="group inline-flex items-center gap-1.5 rounded-md border border-[var(--border)]/60 bg-[var(--card)]/60 px-2.5 py-1 text-[11.5px] font-medium text-[var(--muted-foreground)] shadow-sm transition-colors hover:border-[var(--primary)]/40 hover:bg-[var(--primary)]/5 hover:text-[var(--primary)] disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-[var(--border)]/60 disabled:hover:bg-[var(--card)]/60 disabled:hover:text-[var(--muted-foreground)]"
      >
        <Zap
          size={12}
          strokeWidth={1.8}
          className="shrink-0 transition-colors group-hover:text-[var(--primary)] group-disabled:group-hover:text-[var(--muted-foreground)]"
        />
        <span>{triggered ? t("Answering…") : t("Answer now")}</span>
      </button>
    </div>
  );
});

AnswerNowRow.displayName = "AnswerNowRow";

function CostFooter({
  cost,
  tokens,
  calls,
}: {
  cost: number;
  tokens: number;
  calls: number;
}) {
  const { t } = useTranslation();
  const formatCost = (usd: number) => {
    if (usd < 0.01) return `$${usd.toFixed(4)}`;
    return `$${usd.toFixed(2)}`;
  };
  const formatTokens = (n: number) => {
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return String(n);
  };
  return (
    <div className="flex items-center gap-2 text-[10px] text-[var(--muted-foreground)]/40">
      <Coins size={10} strokeWidth={1.5} className="shrink-0" />
      <span>{formatCost(cost)}</span>
      <span className="opacity-40">·</span>
      <span>
        {formatTokens(tokens)} {t("tokens")}
      </span>
      <span className="opacity-40">·</span>
      <span>
        {calls} {t("calls")}
      </span>
    </div>
  );
}

function RoughActionButton({
  icon: Icon,
  label,
  onClick,
  disabled,
}: {
  icon: LucideIcon;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1 px-0.5 py-0.5 text-[11px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-35"
    >
      <Icon size={11} strokeWidth={1.5} />
      <span>{label}</span>
    </button>
  );
}

const UserMessage = memo(function UserMessage({
  msg,
  index,
  onPreviewAttachment,
}: {
  msg: ChatMessageItem;
  index: number;
  onPreviewAttachment?: (attachment: MessageAttachment) => void;
}) {
  const { t } = useTranslation();
  if (msg.content.startsWith("[Quiz Performance]")) return null;

  return (
    <div key={`${msg.role}-${index}`} className="flex justify-end">
      <div className="max-w-[75%] space-y-1.5">
        <div className="flex justify-end pr-1">
          <span className="text-[10px] tracking-wide text-[var(--muted-foreground)]">
            {t(getModeBadgeLabel(msg.capability))}
          </span>
        </div>
        {msg.attachments?.some((a) => a.type === "image") && (
          <div className="flex flex-wrap justify-end gap-2">
            {msg.attachments
              .filter((a) => a.type === "image" && (a.base64 || a.url))
              .map((a, ai) => {
                const src = imageSrcForAttachment(a);
                if (!src) return null;
                return (
                  <button
                    key={`img-${ai}`}
                    type="button"
                    onClick={() => onPreviewAttachment?.(a)}
                    title={a.filename || t("image")}
                    className="overflow-hidden rounded-2xl border border-[var(--border)] transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={src}
                      alt={a.filename || t("image")}
                      className="max-h-48 max-w-[280px] rounded-2xl object-contain"
                    />
                  </button>
                );
              })}
          </div>
        )}
        {msg.attachments?.some((a) => a.type !== "image") && (
          <div className="flex flex-wrap justify-end gap-2">
            {msg.attachments
              .filter((a) => a.type !== "image")
              .map((a, ai) => {
                const filename = a.filename || t("Attachment");
                const spec = docIconFor(filename);
                const Icon = spec.Icon;
                const cardClass =
                  "flex h-14 w-[220px] items-center gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--card)] px-2.5 text-left shadow-sm transition-colors hover:border-[var(--primary)]/40 hover:bg-[var(--muted)]/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40";
                return (
                  <button
                    key={`doc-${ai}`}
                    type="button"
                    onClick={() => onPreviewAttachment?.(a)}
                    title={filename}
                    className={cardClass}
                  >
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-[var(--muted)]/60">
                      <Icon size={20} strokeWidth={1.5} className={spec.tint} />
                    </div>
                    <div className="min-w-0 flex-1 text-left">
                      <div className="truncate text-[12px] font-medium text-[var(--foreground)]">
                        {filename}
                      </div>
                      <div className="truncate text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
                        {spec.label}
                      </div>
                    </div>
                  </button>
                );
              })}
          </div>
        )}
        <div className="rounded-2xl bg-[var(--secondary)] px-4 py-2.5 text-[14px] leading-relaxed text-[var(--foreground)] shadow-sm">
          {(() => {
            const snap = msg.requestSnapshot;
            const hasNotebook = Boolean(snap?.notebookReferences?.length);
            const hasBooks = Boolean(snap?.bookReferences?.length);
            const hasHistory = Boolean(snap?.historyReferences?.length);
            const hasQuestions = Boolean(
              snap?.questionNotebookReferences?.length,
            );
            const hasSkills = Boolean(snap?.skills?.length);
            const hasMemory = Boolean(snap?.memoryReferences?.length);
            if (
              !hasNotebook &&
              !hasBooks &&
              !hasHistory &&
              !hasQuestions &&
              !hasSkills &&
              !hasMemory
            )
              return null;
            return (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {snap?.notebookReferences?.map((ref) => (
                  <span
                    key={ref.notebook_id}
                    className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)]/60 px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)]"
                  >
                    <BookOpen size={11} strokeWidth={1.8} />
                    {t("Notebook")} · {ref.record_ids.length} {t("records")}
                  </span>
                ))}
                {snap?.bookReferences?.map((ref) => (
                  <span
                    key={ref.book_id}
                    className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)]/60 px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)]"
                  >
                    <BookOpen size={11} strokeWidth={1.8} />
                    {t("Book")} · {ref.page_ids.length} {t("chapters")}
                  </span>
                ))}
                {snap?.historyReferences?.map((sid) => (
                  <span
                    key={sid}
                    className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)]/60 px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)]"
                  >
                    <MessageSquare size={11} strokeWidth={1.8} />
                    {t("Chat History")}
                  </span>
                ))}
                {hasQuestions && (
                  <span className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)]/60 px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)]">
                    <ClipboardList size={11} strokeWidth={1.8} />
                    {t("Question Bank")} ·{" "}
                    {snap?.questionNotebookReferences?.length} {t("items")}
                  </span>
                )}
                {snap?.skills?.map((skill) => (
                  <span
                    key={skill}
                    className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)]/60 px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)]"
                  >
                    <Wand2 size={11} strokeWidth={1.8} />
                    {skill === "auto" ? t("Skills Auto") : skill}
                  </span>
                ))}
                {snap?.memoryReferences?.map((file) => (
                  <span
                    key={file}
                    className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)]/60 px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)]"
                  >
                    <Brain size={11} strokeWidth={1.8} />
                    {t("Memory")} ·{" "}
                    {file === "summary" ? t("Summary") : t("Profile")}
                  </span>
                ))}
              </div>
            );
          })()}
          <div className="whitespace-pre-wrap">{msg.content}</div>
        </div>
      </div>
    </div>
  );
});

UserMessage.displayName = "UserMessage";

export const SpaceContextChips = memo(function SpaceContextChips({
  historySessions,
  bookReferences,
  notebookGroups,
  questionEntries,
  selectedSkills,
  skillsAutoMode,
  memoryFiles,
  onRemoveHistory,
  onRemoveBookReference,
  onRemoveNotebook,
  onRemoveQuestion,
  onRemoveSkill,
  onClearSkillsAuto,
  onRemoveMemoryFile,
}: {
  historySessions: SelectedHistorySession[];
  bookReferences: SelectedBookReference[];
  notebookGroups: NotebookReferenceGroup[];
  questionEntries: SelectedQuestionEntry[];
  selectedSkills: string[];
  skillsAutoMode: boolean;
  memoryFiles: SpaceMemoryFile[];
  onRemoveHistory: (sessionId: string) => void;
  onRemoveBookReference: (bookId: string) => void;
  onRemoveNotebook: (notebookId: string) => void;
  onRemoveQuestion: (entryId: number) => void;
  onRemoveSkill: (skill: string) => void;
  onClearSkillsAuto: () => void;
  onRemoveMemoryFile: (file: SpaceMemoryFile) => void;
}) {
  const { t } = useTranslation();
  if (
    historySessions.length === 0 &&
    bookReferences.length === 0 &&
    notebookGroups.length === 0 &&
    questionEntries.length === 0 &&
    selectedSkills.length === 0 &&
    !skillsAutoMode &&
    memoryFiles.length === 0
  )
    return null;

  return (
    <div className="mb-3 flex flex-wrap gap-2">
      {historySessions.map((session) => (
        <span
          key={session.sessionId}
          className="inline-flex max-w-full items-center gap-2 rounded-xl border border-sky-200 bg-sky-50 px-3 py-1.5 text-[12px] text-sky-800 shadow-sm dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200"
        >
          <MessageSquare size={12} strokeWidth={1.8} className="shrink-0" />
          <span className="shrink-0 font-medium">{t("Chat History")}</span>
          <span className="truncate text-sky-700/90 dark:text-sky-200/90">
            {session.title}
          </span>
          <button
            onClick={() => onRemoveHistory(session.sessionId)}
            className="shrink-0 opacity-60 transition hover:opacity-100"
          >
            <X size={12} />
          </button>
        </span>
      ))}
      {bookReferences.map((book) => (
        <span
          key={book.bookId}
          className="inline-flex max-w-full items-center gap-2 rounded-xl border border-teal-200 bg-teal-50 px-3 py-1.5 text-[12px] text-teal-800 shadow-sm dark:border-teal-900/60 dark:bg-teal-950/30 dark:text-teal-200"
        >
          <BookOpen size={12} strokeWidth={1.8} className="shrink-0" />
          <span className="shrink-0 font-medium">{t("Book")}</span>
          <span className="truncate text-teal-700/90 dark:text-teal-200/90">
            {book.bookTitle} ({book.pages.length})
          </span>
          <button
            onClick={() => onRemoveBookReference(book.bookId)}
            className="shrink-0 opacity-60 transition hover:opacity-100"
          >
            <X size={12} />
          </button>
        </span>
      ))}
      {notebookGroups.map((group) => (
        <span
          key={group.notebookId}
          className="inline-flex max-w-full items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[12px] text-[var(--foreground)] shadow-sm"
        >
          <BookOpen size={12} strokeWidth={1.8} className="shrink-0" />
          <span className="shrink-0 font-medium">{t("Notebook")}</span>
          <span className="truncate text-[var(--muted-foreground)]">
            {group.notebookName} ({group.count})
          </span>
          <button
            onClick={() => onRemoveNotebook(group.notebookId)}
            className="shrink-0 opacity-60 transition hover:opacity-100"
          >
            <X size={12} />
          </button>
        </span>
      ))}
      {questionEntries.map((entry) => (
        <span
          key={entry.id}
          className="inline-flex max-w-full items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-1.5 text-[12px] text-amber-800 shadow-sm dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200"
        >
          <ClipboardList size={12} strokeWidth={1.8} className="shrink-0" />
          <span className="shrink-0 font-medium">{t("Question Bank")}</span>
          <span className="truncate text-amber-700/90 dark:text-amber-200/90">
            {entry.question.length > 40
              ? `${entry.question.slice(0, 40)}…`
              : entry.question}
          </span>
          <button
            onClick={() => onRemoveQuestion(entry.id)}
            className="shrink-0 opacity-60 transition hover:opacity-100"
          >
            <X size={12} />
          </button>
        </span>
      ))}
      {skillsAutoMode && (
        <span className="inline-flex max-w-full items-center gap-2 rounded-xl border border-violet-200 bg-violet-50 px-3 py-1.5 text-[12px] text-violet-800 shadow-sm dark:border-violet-900/60 dark:bg-violet-950/30 dark:text-violet-200">
          <Wand2 size={12} strokeWidth={1.8} className="shrink-0" />
          <span className="shrink-0 font-medium">{t("Skills")}</span>
          <span className="truncate text-violet-700/90 dark:text-violet-200/90">
            {t("Auto")}
          </span>
          <button
            onClick={onClearSkillsAuto}
            className="shrink-0 opacity-60 transition hover:opacity-100"
          >
            <X size={12} />
          </button>
        </span>
      )}
      {selectedSkills.map((skill) => (
        <span
          key={skill}
          className="inline-flex max-w-full items-center gap-2 rounded-xl border border-violet-200 bg-violet-50 px-3 py-1.5 text-[12px] text-violet-800 shadow-sm dark:border-violet-900/60 dark:bg-violet-950/30 dark:text-violet-200"
        >
          <Wand2 size={12} strokeWidth={1.8} className="shrink-0" />
          <span className="shrink-0 font-medium">{t("Skill")}</span>
          <span className="truncate text-violet-700/90 dark:text-violet-200/90">
            {skill}
          </span>
          <button
            onClick={() => onRemoveSkill(skill)}
            className="shrink-0 opacity-60 transition hover:opacity-100"
          >
            <X size={12} />
          </button>
        </span>
      ))}
      {memoryFiles.map((file) => (
        <span
          key={file}
          className="inline-flex max-w-full items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[12px] text-emerald-800 shadow-sm dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200"
        >
          <Brain size={12} strokeWidth={1.8} className="shrink-0" />
          <span className="shrink-0 font-medium">{t("Memory")}</span>
          <span className="truncate text-emerald-700/90 dark:text-emerald-200/90">
            {file === "summary" ? t("Summary") : t("Profile")}
          </span>
          <button
            onClick={() => onRemoveMemoryFile(file)}
            className="shrink-0 opacity-60 transition hover:opacity-100"
          >
            <X size={12} />
          </button>
        </span>
      ))}
    </div>
  );
});

SpaceContextChips.displayName = "SpaceContextChips";

export const ChatMessageList = memo(function ChatMessageList({
  messages,
  isStreaming,
  sessionId,
  language,
  onAnswerNow,
  onCopyAssistantMessage,
  onRegenerateMessage,
  onConfirmOutline,
  onPreviewAttachment,
}: {
  messages: ChatMessageItem[];
  isStreaming: boolean;
  sessionId?: string | null;
  language?: string;
  onAnswerNow: (
    snapshot?: MessageRequestSnapshot,
    assistantMsg?: { content: string; events?: StreamEvent[] },
  ) => void;
  onCopyAssistantMessage: (content: string) => void | Promise<void>;
  onRegenerateMessage: () => void;
  onConfirmOutline?: (
    outline: Array<{ title: string; overview: string }>,
    topic: string,
    researchConfig?: Record<string, unknown> | null,
  ) => void;
  onPreviewAttachment?: (attachment: MessageAttachment) => void;
}) {
  const { t } = useTranslation();
  const outlineStatusByIndex = useMemo(() => {
    const map = new Map<number, "editing" | "researching" | "done">();
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      if (msg.role !== "assistant" || msg.capability !== "deep_research")
        continue;
      const resultEv = msg.events?.find((e) => e.type === "result");
      const meta = resultEv?.metadata as Record<string, unknown> | undefined;
      if (!meta?.outline_preview) continue;
      const hasFollowup = messages
        .slice(i + 1)
        .some(
          (m) => m.role === "assistant" && m.capability === "deep_research",
        );
      if (hasFollowup) {
        const followup = messages
          .slice(i + 1)
          .find(
            (m) => m.role === "assistant" && m.capability === "deep_research",
          );
        const followupResult = followup?.events?.find(
          (e) => e.type === "result",
        );
        map.set(i, followupResult ? "done" : "researching");
      } else if (isStreaming) {
        map.set(i, "researching");
      } else {
        map.set(i, "editing");
      }
    }
    return map;
  }, [messages, isStreaming]);

  const messageRows = useMemo(() => {
    // System messages are backend grounding (e.g. quiz follow-up context) and
    // must never be rendered as a chat bubble. Filter them out defensively in
    // addition to the hydration-time filter in UnifiedChatContext.
    return messages
      .map((msg, index) => ({ msg, originalIndex: index }))
      .filter(({ msg }) => msg.role !== "system")
      .map(({ msg, originalIndex }) => {
        if (msg.role === "user") {
          return {
            msg,
            originalIndex,
            pairedUserMessage: null as ChatMessageItem | null,
          };
        }
        const pairedUserMessage =
          [...messages.slice(0, originalIndex)]
            .reverse()
            .find((previous) => previous.role === "user") ?? null;
        return { msg, originalIndex, pairedUserMessage };
      });
  }, [messages]);

  const lastAssistantIndex = useMemo(() => {
    for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
      if (messages[idx].role === "assistant") return idx;
    }
    return -1;
  }, [messages]);

  return (
    <>
      {messageRows.map(({ msg, originalIndex, pairedUserMessage }) => {
        const i = originalIndex;
        if (msg.role === "user") {
          return (
            <UserMessage
              key={`${msg.role}-${i}`}
              msg={msg}
              index={i}
              onPreviewAttachment={onPreviewAttachment}
            />
          );
        }

        const isActiveAssistant = isStreaming && i === messages.length - 1;
        const msgDone = !isActiveAssistant;
        const showActions = msgDone && hasVisibleMarkdownContent(msg.content);
        const isLastAssistant = i === lastAssistantIndex;
        const showRegenerate =
          showActions &&
          !isStreaming &&
          isLastAssistant &&
          Boolean(pairedUserMessage) &&
          (!pairedUserMessage?.capability ||
            pairedUserMessage?.capability === "chat");

        // The "Answer now" affordance lives inside the trace panel for the
        // currently-streaming assistant turn. We hand the panel a thin
        // closure so it does not need to know about MessageRequestSnapshot.
        const handleTraceAnswerNow =
          isActiveAssistant && pairedUserMessage?.requestSnapshot
            ? () =>
                onAnswerNow(pairedUserMessage.requestSnapshot, {
                  content: msg.content,
                  events: msg.events,
                })
            : undefined;

        const costSummary = (() => {
          if (!msgDone) return null;
          const resultEv = msg.events?.find((e) => e.type === "result");
          if (!resultEv) return null;
          const meta = resultEv.metadata?.metadata as
            | Record<string, unknown>
            | undefined;
          const cs = meta?.cost_summary as
            | {
                total_cost_usd?: number;
                total_tokens?: number;
                total_calls?: number;
              }
            | undefined;
          if (!cs || !cs.total_calls) return null;
          return cs;
        })();

        return (
          <div key={`${msg.role}-${i}`} className="w-full">
            <AssistantMessage
              msg={msg}
              isStreaming={isActiveAssistant}
              outlineStatus={outlineStatusByIndex.get(i)}
              sessionId={sessionId}
              language={language}
              onConfirmOutline={onConfirmOutline}
              onAnswerNow={handleTraceAnswerNow}
            />
            {(showActions || costSummary) && (
              <div className="mt-2 flex items-center">
                {showActions && (
                  <div className="flex gap-2">
                    <RoughActionButton
                      icon={Copy}
                      label={t("Copy")}
                      onClick={() => void onCopyAssistantMessage(msg.content)}
                    />
                    {showRegenerate && (
                      <RoughActionButton
                        icon={RefreshCcw}
                        label={t("Regenerate")}
                        onClick={() => onRegenerateMessage()}
                      />
                    )}
                  </div>
                )}
                {costSummary && (
                  <div className="ml-auto">
                    <CostFooter
                      cost={costSummary.total_cost_usd ?? 0}
                      tokens={costSummary.total_tokens ?? 0}
                      calls={costSummary.total_calls ?? 0}
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
});

ChatMessageList.displayName = "ChatMessageList";
