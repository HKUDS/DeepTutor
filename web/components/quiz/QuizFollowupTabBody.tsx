"use client";

/**
 * QuizFollowupTabBody — chat-page-like surface that lives inside a
 * SessionViewerPanel tab. Dedicated to one quiz question and runs the
 * full ``chat`` capability against a session pinned to that question.
 *
 * Layout: pinned context cards (question / your answer / AI judgment) →
 * scrollable chat thread → ``FollowupChatComposer`` (same chrome as the
 * main chat composer).
 *
 * State is owned by ``QuizFollowupProvider`` so closing/reopening the
 * tab — or toggling questions inside QuizViewer — keeps the thread
 * intact and is reflected in the QuizViewer follow-up badge.
 */

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
} from "react";
import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import FollowupChatComposer from "@/components/quiz/FollowupChatComposer";
import {
  AskUserOptions,
  extractMessageSegments,
} from "@/components/chat/home/AskUserOptions";
import { StreamingStatus, TraceFlow } from "@/components/chat/home/TracePanels";
import { useSmoothStreamText } from "@/hooks/useSmoothStreamText";
import {
  type QuizFollowupTabContext,
  useFollowupThread,
  useQuizFollowupController,
} from "@/context/QuizFollowupContext";
import { apiUrl } from "@/lib/api";
import { getSession } from "@/lib/session-api";

/** Resolve a possibly-relative AttachmentStore URL to an absolute one. */
function resolveImageSrc(url: string | null | undefined): string {
  if (!url) return "";
  if (/^(https?:|data:|blob:)/i.test(url)) return url;
  return apiUrl(url);
}

interface QuizFollowupTabBodyProps {
  context: QuizFollowupTabContext;
}

export default function QuizFollowupTabBody({
  context,
}: QuizFollowupTabBodyProps) {
  const { t } = useTranslation();
  const controller = useQuizFollowupController();
  const thread = useFollowupThread(context.questionKey);
  const threadEndRef = useRef<HTMLDivElement | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const shouldFollowRef = useRef(true);

  // Pin-to-bottom autoscroll: direct ``scrollTop = scrollHeight`` in
  // layout phase, no smooth animation. ``scrollIntoView`` with
  // ``behavior: 'smooth'`` was the previous strategy here, but it
  // races against the next-frame layout update during fast streams
  // (the in-flight animation interrupts itself when a new delta
  // lands and grows the container again), producing the visible
  // jitter we're trying to eliminate. The pin pattern matches what
  // ``useChatAutoScroll`` does on the main chat surface so the two
  // surfaces feel identical mid-stream.
  useLayoutEffect(() => {
    if (!shouldFollowRef.current) return;
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [thread.messages, thread.isStreaming]);

  const handleScroll = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    shouldFollowRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }, []);

  // Hydrate prior chat history when the tab opens and the notebook
  // entry has a persisted ``followup_session_id``. Skipped when the
  // in-memory thread is already populated (page reload while the
  // controller still holds state, or the user toggles the tab).
  useEffect(() => {
    const followupSessionId = context.followupSessionId;
    if (!followupSessionId) return;
    if (thread.messages.length > 0 || thread.sessionId) return;
    let cancelled = false;
    const run = async () => {
      try {
        const detail = await getSession(followupSessionId);
        if (cancelled || !detail) return;
        const hydrated = (detail.messages ?? []).map((m) => ({
          role: m.role,
          content: m.content || "",
          events: m.events ?? [],
        }));
        controller.hydrateThread(
          context.questionKey,
          followupSessionId,
          hydrated,
        );
      } catch {
        /* best-effort — leave the thread empty so the user can re-ask */
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [
    context.followupSessionId,
    context.questionKey,
    controller,
    thread.messages.length,
    thread.sessionId,
  ]);

  const visibleMessages = thread.messages.filter((m) => m.role !== "system");
  const isCoding = context.question.question_type === "coding";

  return (
    <div className="flex h-full flex-col bg-[var(--card)]">
      {/* Header strip — mimics a chat-page title bar but with quiz crumbs. */}
      <div className="flex shrink-0 items-center gap-2 border-b border-[var(--border)]/40 bg-[var(--card)] px-4 py-2.5">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--primary)]/12">
          <Sparkles
            size={14}
            strokeWidth={1.7}
            className="text-[var(--primary)]"
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12.5px] font-semibold text-[var(--foreground)]">
            {context.tabLabel}
          </div>
          <div className="truncate text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Follow-up Chat")}
            {context.question.question_type
              ? ` · ${context.question.question_type}`
              : ""}
          </div>
        </div>
      </div>

      {/* Scrollable body: pinned context + chat thread.
          ``data-chat-scroll-root`` opts this surface into the global
          ``overflow-anchor: none`` + ``scroll-behavior: auto`` rule
          (see app/globals.css) so the manual pin isn't fought by the
          browser's built-in scroll anchoring. */}
      <div
        ref={scrollerRef}
        onScroll={handleScroll}
        data-chat-scroll-root="true"
        className="flex-1 overflow-y-auto px-4 py-3"
      >
        <div className="mx-auto flex max-w-[640px] flex-col gap-3">
          <div className="rounded-md border border-[var(--border)]/70 bg-[var(--background)]/70 px-3 py-2">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
              {t("Question")}
            </div>
            <div className="text-[13px] leading-relaxed text-[var(--foreground)]">
              <MarkdownRenderer
                content={context.question.question}
                variant="compact"
              />
            </div>
          </div>

          <div className="rounded-md border border-[var(--border)]/70 bg-[var(--background)]/70 px-3 py-2">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
              {t("Your Answer")}
            </div>
            {context.userAnswer ? (
              <div className="text-[13px] leading-relaxed text-[var(--foreground)]">
                <MarkdownRenderer
                  content={
                    isCoding &&
                    !context.userAnswer.trimStart().startsWith("```")
                      ? `\`\`\`python\n${context.userAnswer}\n\`\`\``
                      : context.userAnswer
                  }
                  variant="compact"
                />
              </div>
            ) : context.answerImages.length === 0 ? (
              <div className="text-[12px] italic text-[var(--muted-foreground)]">
                {t("No answer recorded.")}
              </div>
            ) : null}
            {context.answerImages.length > 0 && (
              <div className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5">
                {context.answerImages.map((image) => {
                  const src = image.previewUrl ?? resolveImageSrc(image.url);
                  return (
                    <div
                      key={image.id}
                      className="overflow-hidden rounded-md border border-[var(--border)] bg-[var(--card)]"
                    >
                      {src ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={src}
                          alt={image.filename}
                          className="h-16 w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-16 w-full items-center justify-center text-[10px] text-[var(--muted-foreground)]">
                          {image.filename}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {context.aiJudgment && (
            <div className="rounded-md border border-[var(--primary)]/30 bg-[var(--primary)]/[0.04] px-3 py-2">
              <div className="mb-1 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--primary)]">
                <Sparkles size={10} />
                {t("AI Judgment")}
              </div>
              <div className="text-[12.5px] leading-relaxed text-[var(--foreground)]">
                <MarkdownRenderer
                  content={context.aiJudgment}
                  variant="compact"
                />
              </div>
            </div>
          )}

          <div className="flex flex-col gap-3 py-1">
            {visibleMessages.length === 0 ? (
              <div className="rounded-md border border-dashed border-[var(--border)] bg-[var(--background)]/40 px-3 py-3 text-[12px] text-[var(--muted-foreground)]">
                {t(
                  "Ask anything about this question, your answer, or the AI judgment.",
                )}
              </div>
            ) : (
              visibleMessages.map((message, index) => {
                if (message.role === "user") {
                  return (
                    <div key={`user-${index}`} className="flex justify-end">
                      <div className="max-w-[88%] whitespace-pre-wrap break-words rounded-[14px] rounded-br-md bg-[var(--primary)] px-3 py-2 text-[13px] leading-[1.6] text-[var(--primary-foreground)]">
                        {message.content}
                      </div>
                    </div>
                  );
                }
                // Assistant message: render the same inline trace rows the
                // main chat uses (TraceFlow) followed by the message body
                // and the bottom-pinned StreamingStatus row. If
                // the turn paused on ``ask_user``, splice the picker card
                // into the body in stream order — text emitted before the
                // pause sits above the card, text from the resumed
                // iteration sits below.
                const isLast = index === visibleMessages.length - 1;
                const isStreamingThis = isLast && thread.isStreaming;
                return (
                  <AssistantThreadMessage
                    key={`assistant-${index}`}
                    message={message}
                    isStreaming={isStreamingThis}
                    onSubmitUserReply={(reply) =>
                      controller.submitAskUserReply(context.questionKey, reply)
                    }
                  />
                );
              })
            )}
            {thread.error && (
              <div className="rounded-md border border-red-200 bg-red-50 px-2 py-1 text-[11px] text-red-700 dark:border-red-950/50 dark:bg-red-950/20 dark:text-red-300">
                {thread.error}
              </div>
            )}
            <div ref={threadEndRef} />
          </div>
        </div>
      </div>

      {/* Composer — the same ChatComposer used on the main chat page,
          wired through FollowupChatComposer to route sends into the
          QuizFollowupController and keep its own state pool. */}
      <div className="shrink-0 border-t border-[var(--border)]/50 bg-[var(--card)] px-4 pt-3">
        <FollowupChatComposer context={context} />
      </div>
    </div>
  );
}

/**
 * Per-assistant-message renderer for the follow-up thread. Splits the
 * event stream into ordered text + ``ask_user`` segments so the picker
 * card lives inline with the surrounding narration — mirroring the
 * default chat surface's behaviour from ``ChatMessages``.
 */
function AssistantThreadMessage({
  message,
  isStreaming,
  onSubmitUserReply,
}: {
  message: {
    role: "user" | "assistant" | "system";
    content: string;
    events?: import("@/lib/unified-ws").StreamEvent[];
  };
  isStreaming: boolean;
  onSubmitUserReply: (reply: {
    text?: string;
    answers?: Array<{ questionId: string; text: string }>;
  }) => void;
}) {
  const segments = useMemo(
    () => extractMessageSegments(message.events),
    [message.events],
  );
  const hasInlineAskUser = segments.some((s) => s.kind === "ask_user");
  // Smooth the trailing-text growth via the shared rAF typewriter so
  // the markdown renderer sees a steadily-growing string instead of
  // bursty deltas. Off when ``isStreaming`` is false — the hook
  // short-circuits to a pure pass-through in that case.
  const smoothedContent = useSmoothStreamText(message.content, isStreaming);

  return (
    <div className="flex flex-col gap-1.5">
      <TraceFlow events={message.events ?? []} isStreaming={isStreaming} />
      {hasInlineAskUser ? (
        segments.map((seg) =>
          seg.kind === "text" ? (
            seg.text ? (
              <div
                key={seg.key}
                className="text-[13px] leading-[1.6] text-[var(--foreground)]"
              >
                <MarkdownRenderer content={seg.text} variant="compact" />
              </div>
            ) : null
          ) : (
            <AskUserOptions
              key={seg.key}
              data={seg.data}
              onSubmit={onSubmitUserReply}
            />
          ),
        )
      ) : smoothedContent ? (
        <div className="text-[13px] leading-[1.6] text-[var(--foreground)]">
          <MarkdownRenderer content={smoothedContent} variant="compact" />
        </div>
      ) : null}
      {/* Status row pinned to the bottom of the assistant output. */}
      <StreamingStatus
        events={message.events ?? []}
        isStreaming={isStreaming}
        content={message.content}
      />
    </div>
  );
}
