"use client";

import dynamic from "next/dynamic";
import { memo, useMemo } from "react";
import Image from "next/image";
import {
  BookOpen,
  Coins,
  Copy,
  MessageSquare,
  RotateCcw,
  Square,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SelectedHistorySession } from "@/components/chat/HistorySessionPicker";
import AssistantResponse from "@/components/common/AssistantResponse";
import type { MessageRequestSnapshot } from "@/context/UnifiedChatContext";
import { extractMathAnimatorResult } from "@/lib/math-animator-types";
import { extractQuizQuestions } from "@/lib/quiz-types";
import { extractVisualizeResult } from "@/lib/visualize-types";
import type { StreamEvent } from "@/lib/unified-ws";
import { hasVisibleMarkdownContent } from "@/lib/markdown-display";
import { CallTracePanel } from "./TracePanels";

const MathAnimatorViewer = dynamic(
  () => import("@/components/math-animator/MathAnimatorViewer"),
  { ssr: false },
);
const QuizViewer = dynamic(() => import("@/components/quiz/QuizViewer"), { ssr: false });
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
  attachments?: Array<{
    type: string;
    filename?: string;
    base64?: string;
  }>;
  requestSnapshot?: MessageRequestSnapshot;
}

interface NotebookReferenceGroup {
  notebookId: string;
  notebookName: string;
  count: number;
}

function getModeBadgeLabel(capability?: string | null) {
  if (!capability || capability === "chat") return "Chat";
  if (capability === "deep_solve") return "Deep Solve";
  if (capability === "deep_question") return "Quiz Generation";
  if (capability === "deep_research") return "Deep Research";
  if (capability === "math_animator") return "Math Animator";
  if (capability === "visualize") return "Visualize";
  return capability;
}

const AssistantMessage = memo(function AssistantMessage({
  msg,
  isStreaming,
  outlineStatus,
  sessionId,
  language,
  onConfirmOutline,
}: {
  msg: { content: string; capability?: string; events?: StreamEvent[] };
  isStreaming?: boolean;
  outlineStatus?: "editing" | "researching" | "done";
  sessionId?: string | null;
  language?: string;
  onConfirmOutline?: (outline: Array<{ title: string; overview: string }>, topic: string, researchConfig?: Record<string, unknown> | null) => void;
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
      sub_topics: (meta.sub_topics ?? []) as Array<{ title: string; overview: string }>,
      topic: String(meta.topic ?? ""),
      research_config: (meta.research_config ?? null) as Record<string, unknown> | null,
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
      {outlinePreview && outlinePreview.sub_topics.length > 0 ? (
        <ResearchOutlineEditor
          outline={outlinePreview.sub_topics}
          topic={outlinePreview.topic}
          onConfirm={(items) => onConfirmOutline?.(items, outlinePreview.topic, outlinePreview.research_config)}
          status={outlineStatus}
        />
      ) : mathAnimatorResult ? (
        <MathAnimatorViewer result={mathAnimatorResult} />
      ) : visualizeResult ? (
        <VisualizationViewer result={visualizeResult} />
      ) : quizQuestions && quizQuestions.length > 0 ? (
        <QuizViewer questions={quizQuestions} sessionId={sessionId} language={language} />
      ) : (
        <AssistantResponse content={msg.content} />
      )}
    </>
  );
});

AssistantMessage.displayName = "AssistantMessage";

function CostFooter({ cost, tokens, calls }: { cost: number; tokens: number; calls: number }) {
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
      <span>{formatTokens(tokens)} tokens</span>
      <span className="opacity-40">·</span>
      <span>{calls} calls</span>
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

export function ReferenceChips({
  historySessions,
  notebookGroups,
  onRemoveHistory,
  onRemoveNotebook,
}: {
  historySessions: SelectedHistorySession[];
  notebookGroups: NotebookReferenceGroup[];
  onRemoveHistory: (sessionId: string) => void;
  onRemoveNotebook: (notebookId: string) => void;
}) {
  const { t } = useTranslation();
  if (historySessions.length === 0 && notebookGroups.length === 0) return null;

  return (
    <div className="mb-3 flex flex-wrap gap-2">
      {historySessions.map((session) => (
        <span
          key={session.sessionId}
          className="inline-flex max-w-full items-center gap-2 rounded-xl border border-sky-200 bg-sky-50 px-3 py-1.5 text-[12px] text-sky-800 shadow-sm dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200"
        >
          <MessageSquare size={12} strokeWidth={1.8} className="shrink-0" />
          <span className="shrink-0 font-medium">{t("Chat History")}</span>
          <span className="truncate text-sky-700/90 dark:text-sky-200/90">{session.title}</span>
          <button
            onClick={() => onRemoveHistory(session.sessionId)}
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
    </div>
  );
}

export function ChatMessageList({
  messages,
  isStreaming,
  activeUserIndex,
  activeAssistantMessage,
  sessionId,
  language,
  onCancelStreaming,
  onAnswerNow,
  onCopyAssistantMessage,
  onRetryMessage,
  onConfirmOutline,
}: {
  messages: ChatMessageItem[];
  isStreaming: boolean;
  activeUserIndex: number;
  activeAssistantMessage: ChatMessageItem | null;
  sessionId?: string | null;
  language?: string;
  onCancelStreaming: () => void;
  onAnswerNow: (
    snapshot?: MessageRequestSnapshot,
    assistantMsg?: { content: string; events?: StreamEvent[] },
  ) => void;
  onCopyAssistantMessage: (content: string) => void | Promise<void>;
  onRetryMessage: (snapshot?: MessageRequestSnapshot) => void;
  onConfirmOutline?: (outline: Array<{ title: string; overview: string }>, topic: string, researchConfig?: Record<string, unknown> | null) => void;
}) {
  const { t } = useTranslation();
  const outlineStatusByIndex = useMemo(() => {
    const map = new Map<number, "editing" | "researching" | "done">();
    for (let i = 0; i < messages.length; i++) {
      const msg = messages[i];
      if (msg.role !== "assistant" || msg.capability !== "deep_research") continue;
      const resultEv = msg.events?.find((e) => e.type === "result");
      const meta = resultEv?.metadata as Record<string, unknown> | undefined;
      if (!meta?.outline_preview) continue;
      const hasFollowup = messages.slice(i + 1).some(
        (m) => m.role === "assistant" && m.capability === "deep_research",
      );
      if (hasFollowup) {
        const followup = messages.slice(i + 1).find(
          (m) => m.role === "assistant" && m.capability === "deep_research",
        );
        const followupResult = followup?.events?.find((e) => e.type === "result");
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
    return messages.map((msg, index) => {
      if (msg.role === "user") {
        return { msg, pairedUserMessage: null as ChatMessageItem | null };
      }
      const pairedUserMessage =
        [...messages.slice(0, index)].reverse().find((previous) => previous.role === "user") ?? null;
      return { msg, pairedUserMessage };
    });
  }, [messages]);

  return (
    <>
      {messageRows.map(({ msg, pairedUserMessage }, i) => {
        if (msg.role === "user") {
          if (msg.content.startsWith("[Quiz Performance]")) return null;
          const showInlineControls =
            i === activeUserIndex &&
            (!msg.capability || msg.capability === "chat") &&
            Boolean(msg.requestSnapshot) &&
            activeAssistantMessage?.role === "assistant";
          return (
            <div key={`${msg.role}-${i}`} className="flex justify-end">
              <div className="max-w-[75%] space-y-1.5">
                <div className="flex justify-end pr-1">
                  <span className="text-[10px] tracking-wide text-[var(--muted-foreground)]">
                    {getModeBadgeLabel(msg.capability)}
                  </span>
                </div>
                {msg.attachments?.some((a) => a.type === "image") && (
                  <div className="flex flex-wrap justify-end gap-2">
                    {msg.attachments
                      .filter((a) => a.type === "image" && a.base64)
                      .map((a, ai) => (
                        <div key={`img-${ai}`} className="overflow-hidden rounded-2xl border border-[var(--border)]">
                          <Image
                            src={`data:image/png;base64,${a.base64}`}
                            alt={a.filename || t("image")}
                            width={280}
                            height={192}
                            unoptimized
                            className="max-h-48 max-w-[280px] rounded-2xl object-contain"
                          />
                        </div>
                      ))}
                  </div>
                )}
                <div className="rounded-2xl bg-[var(--secondary)] px-4 py-2.5 text-[14px] leading-relaxed text-[var(--foreground)] shadow-sm">
                  {(() => {
                    const snap = msg.requestSnapshot;
                    const hasNotebook = Boolean(snap?.notebookReferences?.length);
                    const hasHistory = Boolean(snap?.historyReferences?.length);
                    if (!hasNotebook && !hasHistory) return null;
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
                        {snap?.historyReferences?.map((sid) => (
                          <span
                            key={sid}
                            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)]/60 px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)]"
                          >
                            <MessageSquare size={11} strokeWidth={1.8} />
                            {t("Chat History")}
                          </span>
                        ))}
                      </div>
                    );
                  })()}
                  <div>{msg.content}</div>
                </div>
                {showInlineControls ? (
                  <div className="flex justify-end gap-2">
                    <RoughActionButton
                      icon={Square}
                      label="Stop"
                      onClick={onCancelStreaming}
                    />
                    <RoughActionButton
                      icon={Zap}
                      label="Answer now"
                      onClick={() =>
                        onAnswerNow(
                          msg.requestSnapshot,
                          activeAssistantMessage?.role === "assistant"
                            ? {
                                content: activeAssistantMessage.content,
                                events: activeAssistantMessage.events,
                              }
                            : undefined,
                        )
                      }
                    />
                  </div>
                ) : null}
              </div>
            </div>
          );
        }

        const msgDone = !isStreaming || i !== messages.length - 1;
        const showActions =
          msgDone && hasVisibleMarkdownContent(msg.content);
        const showRetry =
          showActions &&
          (!pairedUserMessage?.capability || pairedUserMessage?.capability === "chat") &&
          Boolean(pairedUserMessage?.requestSnapshot);

        const costSummary = (() => {
          if (!msgDone) return null;
          const resultEv = msg.events?.find((e) => e.type === "result");
          if (!resultEv) return null;
          const meta = resultEv.metadata?.metadata as Record<string, unknown> | undefined;
          const cs = meta?.cost_summary as { total_cost_usd?: number; total_tokens?: number; total_calls?: number } | undefined;
          if (!cs || !cs.total_calls) return null;
          return cs;
        })();

        return (
          <div key={`${msg.role}-${i}`} className="w-full">
            <AssistantMessage
              msg={msg}
              isStreaming={isStreaming && i === messages.length - 1}
              outlineStatus={outlineStatusByIndex.get(i)}
              sessionId={sessionId}
              language={language}
              onConfirmOutline={onConfirmOutline}
            />
            {(showActions || costSummary) && (
              <div className="mt-2 flex items-center">
                {showActions && (
                  <div className="flex gap-2">
                    <RoughActionButton
                      icon={Copy}
                      label="Copy"
                      onClick={() => void onCopyAssistantMessage(msg.content)}
                    />
                    {showRetry && (
                      <RoughActionButton
                        icon={RotateCcw}
                        label="Retry"
                        onClick={() => onRetryMessage(pairedUserMessage?.requestSnapshot)}
                      />
                    )}
                  </div>
                )}
                {costSummary && (
                  <div className="ml-auto">
                    <CostFooter cost={costSummary.total_cost_usd ?? 0} tokens={costSummary.total_tokens ?? 0} calls={costSummary.total_calls ?? 0} />
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}
