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
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
} from "react";
import {
  HelpCircle,
  MessagesSquare,
  PenLine,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { ACTIVITY_TILE } from "@/components/chat/home/SessionActivityPanel";
import FollowupChatComposer from "@/components/quiz/FollowupChatComposer";
import type { ComposerResourceCatalog } from "@/hooks/useComposerResources";
import type { SideChatResponder } from "@/lib/side-chat";
import {
  AskUserOptions,
  extractMessageSegments,
  leadingTraceEvents,
} from "@/components/chat/home/AskUserOptions";
import { StreamingStatus, TraceFlow } from "@/features/chat/trace";
import { useSmoothStreamText } from "@/hooks/useSmoothStreamText";
import {
  type QuizFollowupTabContext,
  useFollowupThread,
  useQuizFollowupController,
} from "@/context/QuizFollowupContext";
import { apiUrl } from "@/lib/api";
import { isQuoteAttachment, quoteText } from "@/lib/quote-attachments";
import { getSession } from "@/lib/session-api";

/** Resolve a possibly-relative AttachmentStore URL to an absolute one. */
function resolveImageSrc(url: string | null | undefined): string {
  if (!url) return "";
  if (/^(https?:|data:|blob:)/i.test(url)) return url;
  return apiUrl(url);
}

interface QuizFollowupTabBodyProps {
  context: QuizFollowupTabContext;
  resourceCatalog?: ComposerResourceCatalog;
  agents?: { name: string; kind?: string }[];
  /** Hand a side chat to someone else from its composer. */
  onResponderChange?: (responder: SideChatResponder) => void;
}

export default function QuizFollowupTabBody({
  context,
  resourceCatalog,
  agents,
  onResponderChange,
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
          quotes: (m.attachments ?? []).filter(isQuoteAttachment).map(quoteText),
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
  const sideChat = context.sideChat;
  const responder = sideChat?.responder;
  const responderName = !responder || responder.kind === "dito" ? "Dito" : responder.name;

  // The tab pill already names the thread, so the body opens straight on what
  // it is pinned to — no title strip repeating the tab.
  return (
    <div className="flex h-full flex-col bg-[var(--card)]">
      {/* Scrollable body: pinned context + chat thread.
          ``data-chat-scroll-root`` opts this surface into the global
          ``overflow-anchor: none`` + ``scroll-behavior: auto`` rule
          (see app/globals.css) so the manual pin isn't fought by the
          browser's built-in scroll anchoring. */}
      <div
        ref={scrollerRef}
        onScroll={handleScroll}
        data-chat-scroll-root="true"
        className="flex-1 overflow-y-auto px-4 pb-3 pt-1"
      >
        <div className="mx-auto flex max-w-[640px] flex-col gap-2.5">
          {sideChat ? (
            // Beside a draft there is no conversation yet to be about.
            sideChat.parentSessionId ? (
            <PinnedCard icon={MessagesSquare} label={t("About this conversation")}>
              <div className="truncate text-[13px] font-medium text-[var(--foreground)]">
                {sideChat.parentTitle || t("This conversation")}
              </div>
            </PinnedCard>
            ) : null
          ) : (
            <PinnedCard
              icon={HelpCircle}
              label={[t("Question"), context.question.question_type]
                .filter(Boolean)
                .join(" · ")}
            >
              <div className="text-[13px] leading-relaxed text-[var(--foreground)]">
                <MarkdownRenderer
                  content={context.question.question}
                  variant="compact"
                />
              </div>
            </PinnedCard>
          )}

          {!sideChat && (
            <PinnedCard icon={PenLine} label={t("Your Answer")}>
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
                <div className="text-[12.5px] italic text-[var(--muted-foreground)]">
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
                        className="overflow-hidden rounded-lg bg-[var(--card)]"
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
            </PinnedCard>
          )}

          {!sideChat && context.aiJudgment && (
            <PinnedCard icon={Sparkles} label={t("AI Judgment")} tone="primary">
              <div className="text-[12.5px] leading-relaxed text-[var(--foreground)]">
                <MarkdownRenderer
                  content={context.aiJudgment}
                  variant="compact"
                />
              </div>
            </PinnedCard>
          )}

          <div className="flex flex-col gap-3 py-1">
            {visibleMessages.length === 0 ? (
              // What this thread can see, so the first question is asked of
              // the right thing — the composer already says what to type.
              <p className="px-1 text-[12px] leading-[1.6] text-[var(--muted-foreground)]">
                {!responder
                  ? t("Ask why an answer was marked, for another explanation, or for a similar question to try.")
                  : !sideChat?.parentSessionId && responder.kind !== "partner" && responder.kind !== "subagent"
                    ? responder.kind === "partner_group"
                      ? t("Dito brings {{name}} into the discussion here, beside the conversation.", { name: responderName })
                      : t("A conversation with Dito beside the main one. Nothing asked here is added to it.")
                  : responder.kind === "dito"
                    ? t("Dito has read the whole conversation. Nothing asked here is added to it.")
                    : responder.kind === "partner_group"
                      ? t("Dito has read the whole conversation and brings {{name}} into the discussion. Nothing asked here is added to it.", { name: responderName })
                      : t("{{name}} answers here, in its own session, from what you send — quote a passage to ask about it. Nothing asked here is added to the conversation.", { name: responderName })}
              </p>
            ) : (
              visibleMessages.map((message, index) => {
                if (message.role === "user") {
                  return (
                    <div key={`user-${index}`} className="flex justify-end">
                      <div className="max-w-[88%] whitespace-pre-wrap break-words rounded-[14px] rounded-br-md bg-[var(--primary)] px-3 py-2 text-[13px] leading-[1.6] text-[var(--primary-foreground)]">
                        {message.quotes?.map((quote, qi) => (
                          <div
                            key={qi}
                            className="mb-1.5 line-clamp-3 border-l-2 border-[color-mix(in_srgb,var(--primary-foreground)_45%,transparent)] pl-2.5 text-[12.5px] opacity-80"
                          >
                            {quote}
                          </div>
                        ))}
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
              <div role="alert" className="rounded-lg bg-red-50 px-2.5 py-1.5 text-[12px] text-red-700 dark:bg-red-950/20 dark:text-red-300">
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
      <div className="shrink-0 bg-[var(--card)] px-1 pt-1">
        <FollowupChatComposer
          context={context}
          resourceCatalog={resourceCatalog}
          agents={agents}
          onResponderChange={onResponderChange}
        />
      </div>
    </div>
  );
}

/** One thing the thread is pinned to, in the viewer's own tile style. */
function PinnedCard({
  icon: Icon,
  label,
  tone = "neutral",
  children,
}: {
  icon: LucideIcon;
  label: string;
  tone?: "neutral" | "primary";
  children: ReactNode;
}) {
  const primary = tone === "primary";
  return (
    <section
      className={`${
        primary
          ? "rounded-xl bg-[color-mix(in_srgb,var(--primary)_6%,transparent)]"
          : ACTIVITY_TILE
      } px-3.5 pb-3 pt-2.5`}
    >
      <h3
        className={`mb-1.5 flex items-center gap-1.5 text-[11.5px] font-medium ${
          primary ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"
        }`}
      >
        <Icon size={12} strokeWidth={1.8} aria-hidden="true" />
        {label}
      </h3>
      {children}
    </section>
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
    events?: import("@/features/chat/model/protocol").StreamEvent[];
  };
  isStreaming: boolean;
  onSubmitUserReply: (reply: {
    text?: string;
    answers?: Array<{ questionId: string; text: string }>;
  }) => void | boolean | Promise<void | boolean>;
}) {
  const segments = useMemo(
    () =>
      extractMessageSegments(message.events, message.content, {
        streaming: isStreaming,
      }),
    [message.events, message.content, isStreaming],
  );
  const hasInlineAskUser = segments.some((s) => s.kind === "ask_user");
  // Same split as the main chat surface: rounds that ran after a card
  // render below it, so this top trace keeps only what came before.
  const headerTraceEvents = useMemo(
    () => leadingTraceEvents(message.events, segments),
    [message.events, segments],
  );
  // Smooth the trailing-text growth via the shared rAF typewriter so
  // the markdown renderer sees a steadily-growing string instead of
  // bursty deltas. Off when ``isStreaming`` is false — the hook
  // short-circuits to a pure pass-through in that case.
  const smoothedContent = useSmoothStreamText(message.content, isStreaming);

  return (
    <div className="flex flex-col gap-1.5">
      <TraceFlow events={headerTraceEvents} isStreaming={isStreaming} />
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
          ) : seg.kind === "trace" ? (
            <TraceFlow
              key={seg.key}
              events={seg.events}
              isStreaming={isStreaming}
            />
          ) : seg.kind === "ask_user" ? (
            <AskUserOptions
              key={seg.key}
              data={seg.data}
              onSubmit={onSubmitUserReply}
            />
          ) : // A mastery question cannot be posed on this surface: the quiz
          // follow-up chat does not mount the mastery tools.
          null,
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
