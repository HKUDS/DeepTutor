"use client";

import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  collectNarrationCallIds,
  shouldAppendEventContent,
} from "@/lib/stream";
import type { StreamEvent } from "@/lib/unified-ws";

/**
 * v3 ``ask_user`` payload. Mirrors ``deeptutor.tools.ask_user.AskUserPayload``.
 *
 * Every question is rendered as one tab on the card (labelled by its
 * short ``header`` when present); the user can switch between tabs
 * freely, answer each (or skip), and submit once via the footer
 * "Submit answers" button. Options carry a short ``label`` plus an
 * optional ``description`` explaining what picking it implies —
 * mirroring Claude Code's ``AskUserQuestion``. The frontend always
 * carries the v3 shape internally — legacy payloads (plain-string
 * options, single-question) are normalised at extraction time.
 */
export interface AskUserOption {
  label: string;
  description: string | null;
}

export interface AskUserQuestion {
  id: string;
  prompt: string;
  header: string | null;
  multi_select: boolean;
  options: AskUserOption[];
  allow_free_text: boolean;
  placeholder: string | null;
}

export interface AskUserPayload {
  intro: string | null;
  questions: AskUserQuestion[];
}

export interface AskUserAnswer {
  questionId: string;
  /** Empty string = skipped / no answer. */
  text: string;
}

/**
 * Bundled data the chat surface reads from an assistant message's
 * event stream. Always returned together so the card can render in
 * either ``interactive`` (still waiting on user) or ``resolved``
 * (read-only Q&A summary) mode without losing its place in chat
 * history. Returns ``null`` only when the message has no ``ask_user``
 * tool result at all.
 */
export interface AskUserCardData {
  payload: AskUserPayload;
  /** Present when the user has submitted; ``null`` while still pending. */
  answers: AskUserAnswer[] | null;
  resolved: boolean;
}

/**
 * Read the ``ask_user`` card data from an assistant message's events.
 *
 * Walks the events forward (oldest first) so multiple ``ask_user``
 * calls within one turn render as separate Q&A summaries in order.
 * Today only the *latest* unresolved card is interactive; older ones
 * are forced into resolved mode by the corresponding ``progress``
 * event carrying ``ask_user_resolved=true`` (and ideally
 * ``ask_user_tool_call_id``, used to match resolutions to the right
 * question card).
 *
 * Returns the most-recent card so the caller renders one. (Past turns
 * with multiple ask_user calls collapse to the last one — surfacing
 * every one would clutter chat history; the rest are visible in the
 * underlying tool-trace view anyway.)
 */
export function extractAskUserPayload(
  events: StreamEvent[] | undefined,
): AskUserCardData | null {
  if (!events || events.length === 0) return null;

  let latest: {
    payload: AskUserPayload;
    toolCallId: string | null;
  } | null = null;
  let resolution: {
    toolCallId: string | null;
    answers: AskUserAnswer[];
    text: string;
  } | null = null;

  for (const event of events) {
    const meta = (event.metadata ?? {}) as Record<string, unknown>;
    if (event.type === "tool_result") {
      const toolMetadata = meta.tool_metadata;
      if (!toolMetadata || typeof toolMetadata !== "object") continue;
      const askUser = (toolMetadata as Record<string, unknown>).ask_user;
      const normalised = normaliseAskUserPayload(askUser);
      if (!normalised) continue;
      latest = {
        payload: normalised,
        toolCallId:
          (event as { tool_call_id?: string }).tool_call_id ??
          (typeof meta.tool_call_id === "string" ? meta.tool_call_id : null),
      };
      resolution = null;
      continue;
    }
    if (event.type === "progress" && meta.ask_user_resolved) {
      const answersRaw = Array.isArray(meta.answers)
        ? (meta.answers as unknown[])
        : [];
      resolution = {
        toolCallId:
          typeof meta.ask_user_tool_call_id === "string"
            ? meta.ask_user_tool_call_id
            : null,
        answers: answersRaw
          .map((entry) => {
            if (!entry || typeof entry !== "object") return null;
            const obj = entry as Record<string, unknown>;
            const qid = String(obj.questionId || obj.id || "").trim();
            if (!qid) return null;
            return { questionId: qid, text: String(obj.text || "") };
          })
          .filter((a): a is AskUserAnswer => a !== null),
        text:
          typeof meta.reply_preview === "string"
            ? (meta.reply_preview as string)
            : "",
      };
    }
  }

  if (!latest) return null;

  if (
    resolution &&
    (resolution.toolCallId === latest.toolCallId || latest.toolCallId === null)
  ) {
    const answers =
      resolution.answers.length > 0
        ? resolution.answers
        : // Legacy flat-text resolution: backfill as a single synthetic
          // answer attached to the (first) question so the resolved view
          // still has something to display.
          latest.payload.questions.length > 0
          ? [
              {
                questionId: latest.payload.questions[0].id,
                text: resolution.text || "",
              },
            ]
          : [];
    return { payload: latest.payload, answers, resolved: true };
  }

  return { payload: latest.payload, answers: null, resolved: false };
}

/**
 * Interleaved message body. Walks the event stream forward and emits a
 * sequence of segments in the order they were produced, so that text
 * generated before an ``ask_user`` tool result renders ABOVE the card
 * and text generated by the resumed iteration renders BELOW it. The
 * default chat surface uses this instead of pairing a flat
 * ``msg.content`` blob with a card stuck at the bottom.
 *
 * Each ``ask_user`` tool result becomes its own segment with its own
 * resolution state — multiple ask_user calls in one turn render as
 * separate cards in stream order. Only the latest unresolved card is
 * interactive; resolved cards show their Q&A summary.
 */
export type MessageSegment =
  | { kind: "text"; text: string; key: string }
  | {
      kind: "ask_user";
      data: AskUserCardData;
      toolCallId: string | null;
      key: string;
    };

export function extractMessageSegments(
  events: StreamEvent[] | undefined,
): MessageSegment[] {
  if (!events || events.length === 0) return [];

  const segments: MessageSegment[] = [];
  // Index of each ask_user segment by tool_call_id so a later
  // ``progress`` event carrying ``ask_user_resolved`` can flip the
  // matching card to resolved mode without a second pass.
  const byToolCall = new Map<string, number>();
  const seenAskUserCards = new Set<string>();
  let pendingTextIdx: number | null = null;
  let seq = 0;
  // Narration rounds (chat-loop preamble alongside a tool call) stream as
  // content but belong in the trace, not the answer — keep them out of the
  // inline text segments too.
  const narrationCallIds = collectNarrationCallIds(events);

  const ensureTextSegment = () => {
    if (pendingTextIdx === null) {
      pendingTextIdx = segments.length;
      segments.push({ kind: "text", text: "", key: `t${seq++}` });
    }
    return pendingTextIdx;
  };

  for (const event of events) {
    if (shouldAppendEventContent(event)) {
      const callId = ((event.metadata ?? {}) as { call_id?: string }).call_id;
      if (callId && narrationCallIds.has(callId)) continue;
      const idx = ensureTextSegment();
      const seg = segments[idx];
      if (seg.kind === "text") {
        segments[idx] = { ...seg, text: seg.text + event.content };
      }
      continue;
    }
    const meta = (event.metadata ?? {}) as Record<string, unknown>;
    if (event.type === "tool_result") {
      const toolMetadata = meta.tool_metadata;
      if (!toolMetadata || typeof toolMetadata !== "object") continue;
      const askUser = (toolMetadata as Record<string, unknown>).ask_user;
      const normalised = normaliseAskUserPayload(askUser);
      if (!normalised) continue;
      const toolCallId =
        (event as { tool_call_id?: string }).tool_call_id ??
        (typeof meta.tool_call_id === "string" ? meta.tool_call_id : null);
      const cardKey = toolCallId
        ? `call:${toolCallId}`
        : `payload:${JSON.stringify(normalised)}`;
      if (seenAskUserCards.has(cardKey)) continue;
      seenAskUserCards.add(cardKey);
      // Close the current text run so the next text chunk starts a new
      // segment after this card.
      pendingTextIdx = null;
      const idx = segments.length;
      segments.push({
        kind: "ask_user",
        data: { payload: normalised, answers: null, resolved: false },
        toolCallId,
        key: `a${seq++}`,
      });
      if (toolCallId) byToolCall.set(toolCallId, idx);
      continue;
    }
    if (event.type === "progress" && meta.ask_user_resolved) {
      const replyToolCallId =
        typeof meta.ask_user_tool_call_id === "string"
          ? meta.ask_user_tool_call_id
          : null;
      // Match by tool_call_id; fall back to the most recent unresolved
      // ask_user segment if the resolver did not echo the id back.
      let targetIdx =
        replyToolCallId !== null ? (byToolCall.get(replyToolCallId) ?? -1) : -1;
      if (targetIdx < 0) {
        for (let i = segments.length - 1; i >= 0; i--) {
          const s = segments[i];
          if (s.kind === "ask_user" && !s.data.resolved) {
            targetIdx = i;
            break;
          }
        }
      }
      if (targetIdx < 0) continue;
      const target = segments[targetIdx];
      if (target.kind !== "ask_user") continue;
      const answersRaw = Array.isArray(meta.answers)
        ? (meta.answers as unknown[])
        : [];
      const answers: AskUserAnswer[] = answersRaw
        .map((entry) => {
          if (!entry || typeof entry !== "object") return null;
          const obj = entry as Record<string, unknown>;
          const qid = String(obj.questionId || obj.id || "").trim();
          if (!qid) return null;
          return { questionId: qid, text: String(obj.text || "") };
        })
        .filter((a): a is AskUserAnswer => a !== null);
      const replyText =
        typeof meta.reply_preview === "string"
          ? (meta.reply_preview as string)
          : "";
      const finalAnswers =
        answers.length > 0
          ? answers
          : target.data.payload.questions.length > 0
            ? [
                {
                  questionId: target.data.payload.questions[0].id,
                  text: replyText || "",
                },
              ]
            : [];
      segments[targetIdx] = {
        ...target,
        data: {
          payload: target.data.payload,
          answers: finalAnswers,
          resolved: true,
        },
      };
    }
  }

  // Drop empty trailing/leading text segments so the renderer doesn't
  // emit blank ``<AssistantResponse>`` nodes.
  return segments.filter((s) => s.kind !== "text" || s.text.length > 0);
}

/**
 * One option: v3 emits ``{label, description}`` objects; v2 payloads
 * stored in older sessions carry plain strings. Both normalise to the
 * object shape.
 */
function normaliseOption(raw: unknown): AskUserOption | null {
  if (raw && typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    const label = String(o.label ?? "").trim();
    if (!label) return null;
    const description =
      typeof o.description === "string" && o.description.trim()
        ? o.description.trim()
        : null;
    return { label, description };
  }
  const label = String(raw ?? "").trim();
  return label ? { label, description: null } : null;
}

function normaliseAskUserPayload(raw: unknown): AskUserPayload | null {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;

  // v2/v3 shape: ``{intro?, questions: [...]}``
  if (Array.isArray(obj.questions)) {
    const questions: AskUserQuestion[] = [];
    for (const item of obj.questions) {
      if (!item || typeof item !== "object") continue;
      const q = item as Record<string, unknown>;
      const prompt = String(q.prompt ?? q.question ?? "").trim();
      if (!prompt) continue;
      const optionsRaw = Array.isArray(q.options) ? q.options : [];
      questions.push({
        id: String(q.id || `q${questions.length + 1}`),
        prompt,
        header:
          typeof q.header === "string" && q.header.trim()
            ? q.header.trim()
            : null,
        multi_select: Boolean(q.multi_select ?? q.multiSelect),
        options: optionsRaw
          .map(normaliseOption)
          .filter((o): o is AskUserOption => o !== null),
        allow_free_text: q.allow_free_text === false ? false : true,
        placeholder:
          typeof q.placeholder === "string" && q.placeholder.trim()
            ? (q.placeholder as string).trim()
            : null,
      });
    }
    if (questions.length === 0) return null;
    return {
      intro:
        typeof obj.intro === "string" && obj.intro.trim()
          ? (obj.intro as string).trim()
          : null,
      questions,
    };
  }

  // Legacy single-question shape from before the multi-question refactor.
  const prompt = String(obj.question ?? "").trim();
  if (!prompt) return null;
  const optionsRaw = Array.isArray(obj.options) ? obj.options : [];
  return {
    intro: null,
    questions: [
      {
        id: "q1",
        prompt,
        header: null,
        multi_select: false,
        options: optionsRaw
          .map(normaliseOption)
          .filter((o): o is AskUserOption => o !== null),
        allow_free_text: true,
        placeholder: null,
      },
    ],
  };
}

const LETTERS = "ABCDEFGH"; // matches MAX_OPTIONS=8

/**
 * Render the ``ask_user`` card.
 *
 * Two visual modes share the same outer container so the card stays
 * in place in the message stream — never unmounts. Switches from
 * ``interactive`` (the agent is still paused) to ``resolved`` (the
 * user has submitted) once a ``progress`` event with
 * ``ask_user_resolved=true`` arrives in the message events.
 */
export const AskUserOptions = memo(function AskUserOptions({
  data,
  onSubmit,
  collapsible,
  defaultCollapsed,
}: {
  data: AskUserCardData;
  onSubmit: (payload: {
    text?: string;
    answers?: Array<{ questionId: string; text: string }>;
  }) => void;
  /** When true, the resolved Q&A card renders with an inline toggle so
   * the user can hide / show the question + answer summary. Resolved cards
   * default to collapsible+collapsed (the Q&A history stays addressable
   * without dominating the bubble); callers can override explicitly —
   * research keeps its own phase-driven rule. */
  collapsible?: boolean;
  /** Only honoured when ``collapsible`` is true. */
  defaultCollapsed?: boolean;
}) {
  if (data.resolved) {
    return (
      <ResolvedAskUserCard
        payload={data.payload}
        answers={data.answers ?? []}
        collapsible={collapsible ?? true}
        defaultCollapsed={defaultCollapsed ?? true}
      />
    );
  }
  return <InteractiveAskUserCard payload={data.payload} onSubmit={onSubmit} />;
});
AskUserOptions.displayName = "AskUserOptions";

// ---------- interactive mode ----------

const InteractiveAskUserCard = memo(function InteractiveAskUserCard({
  payload,
  onSubmit,
}: {
  payload: AskUserPayload;
  onSubmit: (payload: {
    text?: string;
    answers?: Array<{ questionId: string; text: string }>;
  }) => void;
}) {
  const { t } = useTranslation();
  const totalQuestions = payload.questions.length;

  // Picked option labels per question. Single-select questions hold at
  // most one entry; multi-select questions accumulate toggled labels.
  const [picks, setPicks] = useState<Record<string, string[]>>({});
  // Sticky free-text draft per question. Preserved across option picks
  // and tab switches so the user never loses what they typed.
  const [customText, setCustomText] = useState<Record<string, string>>({});
  // Whether the free-text input is an active choice for a question.
  // Drives both textarea visibility and the "picked" visual state. On
  // multi-select questions it coexists with picked options.
  const [customSelected, setCustomSelected] = useState<Record<string, boolean>>(
    {},
  );
  const [activeIdx, setActiveIdx] = useState(0);
  const [submitted, setSubmitted] = useState(false);

  const activeQuestion = payload.questions[activeIdx] ?? payload.questions[0];

  // Committed answer per question, derived from picks + free text.
  // Multi-select answers join labels with ", " — the same flat string
  // travels to the backend, so the ``{text, answers}`` submit protocol
  // is unchanged.
  const answers = useMemo(() => {
    const out: Record<string, string> = {};
    for (const q of payload.questions) {
      const picked = picks[q.id] ?? [];
      const custom = customSelected[q.id]
        ? (customText[q.id] ?? "").trim()
        : "";
      if (q.multi_select) {
        const parts = [...picked];
        if (custom) parts.push(custom);
        out[q.id] = parts.join(", ");
      } else {
        out[q.id] = customSelected[q.id] ? custom : (picked[0] ?? "");
      }
    }
    return out;
  }, [payload.questions, picks, customText, customSelected]);

  const allAnswered = useMemo(
    () =>
      payload.questions.every((q) => (answers[q.id] ?? "").trim().length > 0),
    [payload.questions, answers],
  );

  const handleSubmit = useCallback(() => {
    if (submitted) return;
    setSubmitted(true);
    const list: Array<{ questionId: string; text: string }> =
      payload.questions.map((q) => ({
        questionId: q.id,
        text: (answers[q.id] ?? "").trim(),
      }));
    // Always include a flat ``text`` synopsis for back-compat with any
    // older server path that only looks at ``text``.
    const flat = list
      .map(({ text }) => text || "(skipped)")
      .filter((s) => s !== "(skipped)")
      .join(" | ");
    onSubmit({ text: flat, answers: list });
  }, [submitted, payload.questions, answers, onSubmit]);

  const pickOption = useCallback(
    (question: AskUserQuestion, label: string) => {
      const qid = question.id;
      if (question.multi_select) {
        // Toggle — no auto-advance; the user may pick several.
        setPicks((prev) => {
          const cur = prev[qid] ?? [];
          const next = cur.includes(label)
            ? cur.filter((l) => l !== label)
            : [...cur, label];
          return { ...prev, [qid]: next };
        });
        return;
      }
      setPicks((prev) => ({ ...prev, [qid]: [label] }));
      setCustomSelected((prev) => ({ ...prev, [qid]: false }));
      // Single-select pick answers this question — hop to the next
      // unanswered one so the flow needs no extra "Next" click
      // (mirrors Claude Code's AskUserQuestion card).
      if (totalQuestions > 1) {
        for (let step = 1; step < totalQuestions; step++) {
          const j = (activeIdx + step) % totalQuestions;
          const other = payload.questions[j];
          if (other.id === qid) continue;
          if (!(answers[other.id] ?? "").trim()) {
            setActiveIdx(j);
            break;
          }
        }
      }
    },
    [totalQuestions, activeIdx, payload.questions, answers],
  );

  const selectCustom = useCallback((question: AskUserQuestion) => {
    setCustomSelected((prev) => ({ ...prev, [question.id]: true }));
    if (!question.multi_select) {
      // Mutually exclusive with option picks on single-select.
      setPicks((prev) => ({ ...prev, [question.id]: [] }));
    }
  }, []);

  const updateCustomText = useCallback((qid: string, text: string) => {
    setCustomText((prev) => ({ ...prev, [qid]: text }));
    setCustomSelected((prev) => ({ ...prev, [qid]: true }));
  }, []);

  return (
    <div className="mt-3 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04),0_4px_14px_rgba(0,0,0,0.04)]">
      <div className="flex items-start gap-3">
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--foreground)_8%,transparent)] text-[12px] font-semibold text-[var(--foreground)]/70">
          ?
        </div>
        <div className="flex-1">
          <div className="text-[13px] font-medium leading-snug text-[var(--foreground)]">
            {payload.intro || t("Please answer to continue.")}
          </div>
          <div className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
            {submitted
              ? t("Sending your answers…")
              : totalQuestions > 1
                ? t("{{count}} questions — tap a tab to switch.", {
                    count: totalQuestions,
                  })
                : t("Pick an option or type your own to continue.")}
          </div>
        </div>
      </div>

      {totalQuestions > 1 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {payload.questions.map((q, idx) => {
            const isActive = idx === activeIdx;
            const answered = (answers[q.id] ?? "").trim().length > 0;
            return (
              <button
                key={q.id}
                type="button"
                onClick={() => setActiveIdx(idx)}
                disabled={submitted}
                className={
                  "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition-all " +
                  (isActive
                    ? "border-[var(--foreground)]/35 bg-[color-mix(in_srgb,var(--foreground)_5%,transparent)] text-[var(--foreground)]"
                    : "border-[var(--border)] bg-transparent text-[var(--muted-foreground)] hover:border-[var(--foreground)]/25 hover:text-[var(--foreground)]") +
                  " disabled:cursor-not-allowed disabled:opacity-60"
                }
              >
                <span
                  className={
                    "flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] " +
                    (answered
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "bg-[var(--muted)]/60 text-[var(--muted-foreground)]")
                  }
                >
                  {answered ? "✓" : idx + 1}
                </span>
                <span className="max-w-[160px] truncate">
                  {q.header || q.prompt}
                </span>
              </button>
            );
          })}
        </div>
      ) : null}

      <QuestionBody
        key={activeQuestion.id}
        question={activeQuestion}
        pickedLabels={picks[activeQuestion.id] ?? []}
        customDraft={customText[activeQuestion.id] ?? ""}
        customSelected={!!customSelected[activeQuestion.id]}
        locked={submitted}
        onPickOption={(label) => pickOption(activeQuestion, label)}
        onSelectCustom={() => selectCustom(activeQuestion)}
        onCustomTextChange={(text) => updateCustomText(activeQuestion.id, text)}
      />

      <div className="mt-3 flex items-center justify-between gap-2 border-t border-[var(--border)]/60 pt-3">
        <div className="flex min-w-0 flex-1 items-center">
          {totalQuestions > 1 && activeIdx > 0 ? (
            <button
              type="button"
              onClick={() => setActiveIdx((idx) => Math.max(0, idx - 1))}
              disabled={submitted}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-transparent px-2.5 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--foreground)]/30 hover:bg-[color-mix(in_srgb,var(--foreground)_4%,transparent)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft size={14} strokeWidth={2} />
              <span>{t("Previous question")}</span>
            </button>
          ) : (
            <div className="text-[11.5px] text-[var(--muted-foreground)]">
              {allAnswered
                ? t("All questions answered.")
                : t("Unanswered questions will be submitted as skipped.")}
            </div>
          )}
        </div>
        {totalQuestions > 1 && activeIdx < totalQuestions - 1 ? (
          <button
            type="button"
            onClick={() =>
              setActiveIdx((idx) => Math.min(totalQuestions - 1, idx + 1))
            }
            disabled={submitted}
            className="inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span>{t("Next question")}</span>
            <ChevronRight size={14} strokeWidth={2} />
          </button>
        ) : (
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitted}
            className="rounded-md bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {totalQuestions > 1 ? t("Submit answers") : t("Submit")}
          </button>
        )}
      </div>
    </div>
  );
});
InteractiveAskUserCard.displayName = "InteractiveAskUserCard";

const QuestionBody = memo(function QuestionBody({
  question,
  pickedLabels,
  customDraft,
  customSelected,
  locked,
  onPickOption,
  onSelectCustom,
  onCustomTextChange,
}: {
  question: AskUserQuestion;
  pickedLabels: string[];
  customDraft: string;
  customSelected: boolean;
  locked: boolean;
  onPickOption: (label: string) => void;
  onSelectCustom: () => void;
  onCustomTextChange: (text: string) => void;
}) {
  const { t } = useTranslation();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (customSelected) {
      textareaRef.current?.focus();
    }
  }, [customSelected]);

  return (
    <>
      <div className="mt-3 text-[14px] font-medium leading-snug text-[var(--foreground)]">
        {question.prompt}
        {question.multi_select ? (
          <span className="ml-1.5 text-[11px] font-normal text-[var(--muted-foreground)]">
            {t("Select all that apply.")}
          </span>
        ) : null}
      </div>

      {question.options.length > 0 ? (
        <div className="mt-2 flex flex-col gap-1.5">
          {question.options.map((option, idx) => {
            const letter = LETTERS[idx] ?? String(idx + 1);
            const isPicked = question.multi_select
              ? pickedLabels.includes(option.label)
              : !customSelected && pickedLabels[0] === option.label;
            return (
              <button
                key={`${letter}-${option.label}`}
                type="button"
                onClick={() => !locked && onPickOption(option.label)}
                disabled={locked}
                className={
                  "group flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left transition-all " +
                  (isPicked
                    ? "border-[var(--primary)]/70 bg-[color-mix(in_srgb,var(--primary)_7%,var(--card))] text-[var(--foreground)]"
                    : "border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] hover:border-[var(--foreground)]/30 hover:bg-[color-mix(in_srgb,var(--foreground)_3%,var(--card))]") +
                  " disabled:cursor-not-allowed disabled:opacity-60"
                }
              >
                <span
                  className={
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[12px] font-semibold transition-colors " +
                    (isPicked
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "bg-[var(--muted)]/70 text-[var(--muted-foreground)] group-hover:bg-[color-mix(in_srgb,var(--foreground)_10%,transparent)] group-hover:text-[var(--foreground)]")
                  }
                >
                  {question.multi_select && isPicked ? "✓" : letter}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13.5px] leading-snug">
                    {option.label}
                  </span>
                  {option.description ? (
                    <span className="mt-0.5 block text-[11.5px] leading-snug text-[var(--muted-foreground)]">
                      {option.description}
                    </span>
                  ) : null}
                </span>
              </button>
            );
          })}
        </div>
      ) : null}

      {question.allow_free_text ? (
        <div className="mt-1.5">
          {customSelected ? (
            <div
              className={
                "flex items-start gap-3 rounded-xl border px-3 py-2 transition-colors " +
                "border-[var(--primary)]/70 bg-[color-mix(in_srgb,var(--primary)_5%,var(--card))]"
              }
            >
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--primary)] text-[12px] font-semibold text-[var(--primary-foreground)]">
                {LETTERS[question.options.length] ?? "+"}
              </span>
              <textarea
                ref={textareaRef}
                value={customDraft}
                onChange={(event) => onCustomTextChange(event.target.value)}
                placeholder={question.placeholder ?? t("Type your reply…")}
                rows={3}
                disabled={locked}
                className="min-h-[2.25rem] w-full resize-y bg-transparent text-[13.5px] leading-snug text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/80 disabled:opacity-60"
              />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => !locked && onSelectCustom()}
              disabled={locked}
              className="flex w-full items-center gap-3 rounded-xl border border-dashed border-[var(--border)] bg-transparent px-3 py-2 text-left text-[13px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--foreground)]/30 hover:bg-[color-mix(in_srgb,var(--foreground)_3%,transparent)] hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--muted)]/70 text-[12px] font-semibold text-[var(--muted-foreground)]">
                {LETTERS[question.options.length] ?? "+"}
              </span>
              <span className="truncate">
                {customDraft.trim()
                  ? t("Other: {{text}}", { text: customDraft.trim() })
                  : t("Other — write your own reply…")}
              </span>
            </button>
          )}
        </div>
      ) : null}
    </>
  );
});
QuestionBody.displayName = "QuestionBody";

// ---------- resolved (read-only) mode ----------

const ResolvedAskUserCard = memo(function ResolvedAskUserCard({
  payload,
  answers,
  collapsible,
  defaultCollapsed,
}: {
  payload: AskUserPayload;
  answers: AskUserAnswer[];
  collapsible: boolean;
  defaultCollapsed: boolean;
}) {
  const { t } = useTranslation();
  // Null means "follow defaultCollapsed"; once the user toggles, their
  // explicit choice wins across research-progress re-renders.
  const [manualCollapsed, setManualCollapsed] = useState<boolean | null>(null);
  const collapsed = collapsible ? (manualCollapsed ?? defaultCollapsed) : false;

  const toggleCollapsed = useCallback(() => {
    setManualCollapsed((current) => !(current ?? defaultCollapsed));
  }, [defaultCollapsed]);

  const byId = useMemo(() => {
    const map = new Map<string, string>();
    for (const a of answers) map.set(a.questionId, a.text);
    return map;
  }, [answers]);

  const answeredCount = useMemo(() => {
    let n = 0;
    for (const q of payload.questions) {
      if ((byId.get(q.id) ?? "").trim().length > 0) n += 1;
    }
    return n;
  }, [payload.questions, byId]);

  // Match the look-and-feel of ``ResearchOutlineEditor`` so the two
  // collapsible cards stack consistently in the merged research bubble.
  return (
    <div className="my-2 rounded-lg border border-[var(--border)]/30 bg-[var(--background)] shadow-sm">
      <button
        type="button"
        disabled={!collapsible}
        onClick={collapsible ? toggleCollapsed : undefined}
        className={`block w-full text-left ${collapsed ? "" : "border-b border-[var(--border)]/20"} px-4 py-2 ${
          collapsible
            ? "cursor-pointer transition-colors hover:bg-[var(--muted-foreground)]/[0.025]"
            : "cursor-default"
        }`}
      >
        <div className="flex items-center gap-1.5">
          {collapsible && (
            <ChevronDown
              size={12}
              className={`shrink-0 text-[var(--muted-foreground)]/50 transition-transform ${
                collapsed ? "-rotate-90" : ""
              }`}
            />
          )}
          <h3 className="text-[13px] font-semibold text-[var(--foreground)]">
            {t("Your answers")}
          </h3>
          {collapsible && collapsed && (
            <span className="text-[11px] text-[var(--muted-foreground)]/45">
              · {answeredCount}/{payload.questions.length} {t("answered")}
            </span>
          )}
        </div>
      </button>
      {!collapsed && (
        <div className="space-y-0 divide-y divide-[var(--border)]/15">
          {payload.questions.map((q, index) => {
            const value = (byId.get(q.id) ?? "").trim();
            return (
              <div key={q.id} className="flex items-start gap-2 px-3 py-1.5">
                <span className="mt-[3px] w-4 shrink-0 text-center text-[11px] font-medium tabular-nums leading-tight text-[var(--muted-foreground)]/30">
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1 space-y-0.5">
                  <div className="text-[12px] font-medium leading-snug text-[var(--foreground)]">
                    {q.prompt}
                  </div>
                  <div className="text-[11px] leading-snug text-[var(--muted-foreground)]/70">
                    {value ? (
                      value
                    ) : (
                      <span className="italic">{t("(skipped)")}</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
});
ResolvedAskUserCard.displayName = "ResolvedAskUserCard";
