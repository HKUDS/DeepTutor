"use client";

import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCardSubmission } from "@/hooks/use-card-submission";
import { REPLY_NOT_DELIVERED } from "@/lib/ask-user-state";
import { decodeEscapedUnicodeForDisplay } from "@/lib/markdown-display";
import {
  readPosedQuestion,
  type MasteryQuestion,
} from "@/lib/mastery-question";
import {
  collectNarrationCallIds,
  shouldAppendEventContent,
} from "@/lib/stream";
import type { StreamEvent } from "@/features/chat/model/protocol";

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
  /**
   * The model is still writing this call's arguments: the card is a preview
   * built from partial JSON (``ask_user_draft`` events) and its options may
   * still be half a word long. It renders read-only until the dispatched
   * ``tool_result`` replaces it with the real payload — answering a question
   * that is not finished being asked would submit against a card the backend
   * has never seen.
   */
  streaming?: boolean;
}

/**
 * A preview and its dispatched call agree on this identity. Responses-API
 * calls are dispatched under ``"<call id>|<output item id>"`` while the
 * argument deltas that built the preview only ever carry the call id, so the
 * suffix is dropped on both sides.
 */
function askUserCallKey(id: string | null): string | null {
  if (!id) return null;
  const [callId] = id.split("|", 1);
  return callId || null;
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
/**
 * The card preview an ``ask_user_draft`` event carries, if it has one.
 *
 * Emitted by the backend while the model writes the call's arguments, so the
 * card can appear with its intro and grow its options in place rather than
 * landing whole after a silent pause. Returns the payload plus the call it
 * previews, so the dispatched result can replace the right card.
 */
function readAskUserDraft(
  event: StreamEvent,
): { payload: AskUserPayload; callKey: string | null } | null {
  if (event.type !== "progress") return null;
  const meta = (event.metadata ?? {}) as Record<string, unknown>;
  const draft = meta.ask_user_draft;
  if (!draft || typeof draft !== "object") return null;
  const payload = normaliseAskUserPayload(draft, { allowNoQuestions: true });
  if (!payload) return null;
  return {
    payload,
    callKey: askUserCallKey(
      typeof meta.draft_call_id === "string" ? meta.draft_call_id : null,
    ),
  };
}

export function extractAskUserPayload(
  events: StreamEvent[] | undefined,
  /**
   * ``streaming`` is the turn's state. A card the model was still writing is
   * only offered while that turn is running: once it has settled, a preview
   * that never became a dispatched call is a card nobody can answer. See
   * ``extractMessageSegments``, which drops such a segment for the same
   * reason.
   */
  { streaming = false }: { streaming?: boolean } = {},
): AskUserCardData | null {
  if (!events || events.length === 0) return null;

  let latest: {
    payload: AskUserPayload;
    toolCallId: string | null;
    streaming?: boolean;
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
    const draft = streaming ? readAskUserDraft(event) : null;
    if (draft) {
      // A preview only ever stands in for a card that has not been
      // dispatched yet; the real result overwrites it above.
      latest = {
        payload: draft.payload,
        toolCallId: draft.callKey,
        streaming: true,
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

  return {
    payload: latest.payload,
    answers: null,
    resolved: false,
    streaming: latest.streaming ?? false,
  };
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
 *
 * The text comes from the ``content`` events while the turn streams. Once it
 * has settled, the message keeps only a semantic preview of its trace — tool
 * calls, cards, the terminal frame — and the session endpoint serves the same
 * preview on reload, so there are no content events left to read. The answer
 * itself still lives in ``answerContent``; pass it, and when the events carry
 * no text the body is laid out from it instead, split around each card at the
 * ``assistant_content_offset`` its resolution was stamped with. A card with no
 * offset takes the whole remaining text above it, which is exact for a card
 * that ended its turn (a mastery question) and the natural reading order for
 * anything older that was never stamped.
 */
export type MessageSegment =
  | { kind: "text"; text: string; key: string }
  | {
      kind: "ask_user";
      data: AskUserCardData;
      toolCallId: string | null;
      key: string;
    }
  /**
   * A posed mastery question. Its own segment, not an `ask_user` one with a
   * marker on it: the study card it renders needs the objective, the attempt
   * and the verdict, and it is answered by the next message rather than by
   * resolving this turn's pause. `lib/mastery-question` owns the shape; this
   * layout only places it.
   */
  | {
      kind: "mastery_question";
      question: MasteryQuestion;
      toolCallId: string | null;
      key: string;
    }
  /**
   * The trace of the round(s) that ran AFTER a card — the reasoning the
   * resumed turn produced once the user answered. It renders below the
   * card it followed, because the message's activity block is pinned to
   * the top: everything emitted after a submit used to land back up
   * there, above content the user had already scrolled past, so the
   * turn looked frozen after they picked an option.
   */
  | { kind: "trace"; events: StreamEvent[]; key: string };

export function extractMessageSegments(
  events: StreamEvent[] | undefined,
  answerContent = "",
  /**
   * ``streaming`` is the turn's own state, not a card's. A preview card is
   * kept only while the turn that is writing it is still running: once the
   * turn has settled, a preview that never became a dispatched call is a
   * card nobody can answer, so it is dropped rather than left in history.
   * (Previews are not part of a persisted turn's event preview either, so a
   * reloaded message never has one to begin with.)
   */
  { streaming = false }: { streaming?: boolean } = {},
): MessageSegment[] {
  if (!events || events.length === 0) return [];

  const segments: MessageSegment[] = [];
  // Where each card sits in the answer text, by segment index, when its
  // events say so. Only needed for the settled layout below.
  const answerOffsets = new Map<number, number>();
  // Index of each ask_user segment by tool_call_id so a later
  // ``progress`` event carrying ``ask_user_resolved`` can flip the
  // matching card to resolved mode without a second pass.
  const byToolCall = new Map<string, number>();
  const seenAskUserCards = new Set<string>();
  // Preview cards, by the call they preview, so each successive draft
  // updates its own card in place and the dispatched result later replaces
  // that same segment — the card never unmounts and never duplicates.
  const draftsByCall = new Map<string, number>();
  // Where the preview whose call id never arrived lives, if any: a provider
  // that streams arguments without a call id still gets one growing card.
  let anonymousDraftIdx: number | null = null;
  let pendingTextIdx: number | null = null;
  let pendingTraceIdx: number | null = null;
  let sawAskUser = false;
  let seq = 0;
  // Narration rounds (chat-loop preamble alongside a tool call) stream as
  // content but belong in the trace, not the answer — keep them out of the
  // inline text segments too.
  const narrationCallIds = collectNarrationCallIds(events);

  const ensureTextSegment = () => {
    pendingTraceIdx = null;
    if (pendingTextIdx === null) {
      pendingTextIdx = segments.length;
      segments.push({ kind: "text", text: "", key: `t${seq++}` });
    }
    return pendingTextIdx;
  };

  /** Collect one post-card trace event; a no-op before the first card. */
  const appendTraceEvent = (event: StreamEvent) => {
    if (!sawAskUser) return;
    if (pendingTraceIdx === null) {
      pendingTraceIdx = segments.length;
      segments.push({ kind: "trace", events: [], key: `r${seq++}` });
    }
    const seg = segments[pendingTraceIdx];
    if (seg.kind === "trace") seg.events.push(event);
  };

  for (const event of events) {
    if (shouldAppendEventContent(event)) {
      const callId = ((event.metadata ?? {}) as { call_id?: string }).call_id;
      if (callId && narrationCallIds.has(callId)) {
        appendTraceEvent(event);
        continue;
      }
      const idx = ensureTextSegment();
      const seg = segments[idx];
      if (seg.kind === "text") {
        segments[idx] = { ...seg, text: seg.text + event.content };
      }
      continue;
    }
    const meta = (event.metadata ?? {}) as Record<string, unknown>;
    if (event.type === "tool_result") {
      const posed = readPosedQuestion(event);
      if (posed) {
        const cardKey = `mastery:${posed.questionId}`;
        if (seenAskUserCards.has(cardKey)) continue;
        seenAskUserCards.add(cardKey);
        // Same bookkeeping as a card below: close the text run so the round's
        // remaining prose starts fresh underneath, and open the post-card
        // trace region.
        pendingTextIdx = null;
        pendingTraceIdx = null;
        sawAskUser = true;
        const masteryIdx = segments.length;
        segments.push({
          kind: "mastery_question",
          question: posed,
          toolCallId:
            (event as { tool_call_id?: string }).tool_call_id ??
            (typeof meta.tool_call_id === "string" ? meta.tool_call_id : null),
          key: `m${seq++}`,
        });
        if (typeof meta.assistant_content_offset === "number") {
          answerOffsets.set(masteryIdx, meta.assistant_content_offset);
        }
        continue;
      }
      const toolMetadata = meta.tool_metadata;
      const askUser =
        toolMetadata && typeof toolMetadata === "object"
          ? (toolMetadata as Record<string, unknown>).ask_user
          : null;
      const normalised = normaliseAskUserPayload(askUser);
      if (!normalised) {
        // Any other tool's result is trace material for the region.
        appendTraceEvent(event);
        continue;
      }
      const toolCallId =
        (event as { tool_call_id?: string }).tool_call_id ??
        (typeof meta.tool_call_id === "string" ? meta.tool_call_id : null);
      const cardKey = toolCallId
        ? `call:${toolCallId}`
        : `payload:${JSON.stringify(normalised)}`;
      if (seenAskUserCards.has(cardKey)) continue;
      seenAskUserCards.add(cardKey);
      // Close the current text and trace runs so what the resumed round
      // emits starts fresh segments below this card.
      pendingTextIdx = null;
      pendingTraceIdx = null;
      sawAskUser = true;
      // This call was previewed while it streamed: promote that card rather
      // than appending a second one. Keeping the segment's key keeps the
      // rendered card mounted, so the picked-option state and scroll
      // position survive the swap from preview to answerable.
      const callKey = askUserCallKey(toolCallId);
      const draftIdx: number =
        (callKey !== null ? draftsByCall.get(callKey) : undefined) ??
        anonymousDraftIdx ??
        -1;
      const draftSegment = draftIdx >= 0 ? segments[draftIdx] : null;
      if (draftSegment && draftSegment.kind === "ask_user") {
        segments[draftIdx] = {
          ...draftSegment,
          data: { payload: normalised, answers: null, resolved: false },
          toolCallId,
        };
        if (callKey !== null) draftsByCall.delete(callKey);
        if (draftIdx === anonymousDraftIdx) anonymousDraftIdx = null;
        if (toolCallId) byToolCall.set(toolCallId, draftIdx);
        if (typeof meta.assistant_content_offset === "number") {
          answerOffsets.set(draftIdx, meta.assistant_content_offset);
        }
        continue;
      }
      const idx = segments.length;
      segments.push({
        kind: "ask_user",
        data: { payload: normalised, answers: null, resolved: false },
        toolCallId,
        key: `a${seq++}`,
      });
      if (toolCallId) byToolCall.set(toolCallId, idx);
      if (typeof meta.assistant_content_offset === "number") {
        answerOffsets.set(idx, meta.assistant_content_offset);
      }
      continue;
    }
    const draft = readAskUserDraft(event);
    if (draft) {
      const existingIdx =
        (draft.callKey !== null
          ? draftsByCall.get(draft.callKey)
          : undefined) ??
        (draft.callKey === null ? (anonymousDraftIdx ?? undefined) : undefined);
      if (existingIdx !== undefined) {
        const existing = segments[existingIdx];
        if (existing.kind === "ask_user") {
          segments[existingIdx] = {
            ...existing,
            data: {
              payload: draft.payload,
              answers: null,
              resolved: false,
              streaming: true,
            },
          };
        }
        continue;
      }
      pendingTextIdx = null;
      // Deliberately *not* setting ``sawAskUser``: the trace events that
      // belong to this very call are still ahead of us in the stream, and
      // ``leadingTraceEvents`` renders them above the bubble. Opening the
      // post-card trace run here showed them a second time *below* the card
      // — so the call's own "asking you" step read as happening after the
      // question it produced. The dispatched result below owns that switch.
      const idx = segments.length;
      segments.push({
        kind: "ask_user",
        data: {
          payload: draft.payload,
          answers: null,
          resolved: false,
          streaming: true,
        },
        toolCallId: draft.callKey,
        key: `a${seq++}`,
      });
      if (draft.callKey !== null) draftsByCall.set(draft.callKey, idx);
      else anonymousDraftIdx = idx;
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
      if (typeof meta.assistant_content_offset === "number") {
        answerOffsets.set(targetIdx, meta.assistant_content_offset);
      }
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
      // The resolution belongs to the card, not to the trace below it.
      continue;
    }
    appendTraceEvent(event);
  }

  // The turn is over: a preview still marked streaming never became a
  // dispatched call (a duplicate parallel ask_user, a guard that rejected the
  // arguments), so there is nothing behind it to answer. Dropping it shifts
  // the segment indices ``answerOffsets`` is keyed by, so both are rebuilt
  // together.
  let kept = segments;
  let keptOffsets = answerOffsets;
  if (!streaming && segments.some((s) => s.kind === "ask_user" && s.data.streaming)) {
    kept = [];
    keptOffsets = new Map<number, number>();
    segments.forEach((segment, idx) => {
      if (segment.kind === "ask_user" && segment.data.streaming) return;
      const offset = answerOffsets.get(idx);
      if (offset !== undefined) keptOffsets.set(kept.length, offset);
      kept.push(segment);
    });
  }

  const textFromEvents = kept.some(
    (s) => s.kind === "text" && s.text.length > 0,
  );
  const laidOut =
    !textFromEvents && sawAskUser && answerContent
      ? layOutAnswerContent(kept, answerContent, keptOffsets)
      : kept;

  // Drop empty trailing/leading text segments so the renderer doesn't
  // emit blank ``<AssistantResponse>`` nodes, and trace regions whose
  // events all turned out to be unrenderable.
  return laidOut.filter((s) =>
    s.kind === "text"
      ? s.text.length > 0
      : s.kind !== "trace" || s.events.length > 0,
  );
}

/**
 * Lay the persisted answer out around the cards of a settled message.
 *
 * Each card takes the text between the previous cut and its own offset; the
 * text past the last cut trails after everything. Offsets are read in order
 * and never move backwards, so a stray value cannot reorder the body.
 */
function layOutAnswerContent(
  segments: MessageSegment[],
  answerContent: string,
  answerOffsets: Map<number, number>,
): MessageSegment[] {
  const laidOut: MessageSegment[] = [];
  let cursor = 0;
  let textKey = 0;
  const pushText = (end: number) => {
    if (end <= cursor) return;
    laidOut.push({
      kind: "text",
      text: answerContent.slice(cursor, end),
      key: `c${textKey++}`,
    });
    cursor = end;
  };
  segments.forEach((segment, idx) => {
    if (segment.kind === "text") return;
    if (segment.kind === "ask_user" || segment.kind === "mastery_question") {
      const offset = answerOffsets.get(idx);
      pushText(
        offset === undefined
          ? answerContent.length
          : snapToLineStart(answerContent, Math.max(cursor, offset)),
      );
    }
    laidOut.push(segment);
  });
  pushText(answerContent.length);
  return laidOut;
}

/**
 * The offset was measured on the answer as streamed; the stored text may have
 * gained a few characters since (the CJK emphasis repair inserts spaces). A
 * card follows a paragraph in practice, so a line start within a few
 * characters is the boundary meant — anything farther is left alone.
 */
const OFFSET_SNAP_WINDOW = 8;

function snapToLineStart(content: string, offset: number): number {
  const clamped = Math.max(0, Math.min(offset, content.length));
  if (
    clamped === 0 ||
    clamped === content.length ||
    content[clamped - 1] === "\n"
  ) {
    return clamped;
  }
  let best = clamped;
  let bestDistance = Number.POSITIVE_INFINITY;
  const lo = Math.max(1, clamped - OFFSET_SNAP_WINDOW);
  const hi = Math.min(content.length, clamped + OFFSET_SNAP_WINDOW);
  for (let i = lo; i <= hi; i += 1) {
    if (content[i - 1] !== "\n") continue;
    const distance = Math.abs(i - clamped);
    if (distance < bestDistance) {
      best = i;
      bestDistance = distance;
    }
  }
  // A paragraph break is a run of newlines; the cut belongs after all of it.
  while (best < content.length && content[best] === "\n") best += 1;
  return best;
}

/**
 * The events whose trace rows still belong to the message's top activity
 * block: everything the segments did not claim for a post-card region.
 * Pass it as ``AssistantActivity``'s ``traceEvents`` (or to a bare
 * ``TraceFlow``) so a resumed round's reasoning is not shown twice — once
 * where the user is looking, and once back above the card.
 */
export function leadingTraceEvents(
  events: StreamEvent[] | undefined,
  segments: MessageSegment[],
): StreamEvent[] {
  const claimed = new Set<StreamEvent>();
  for (const segment of segments) {
    if (segment.kind !== "trace") continue;
    for (const event of segment.events) claimed.add(event);
  }
  return (events ?? []).filter((event) => !claimed.has(event));
}

/**
 * Decode dense JSON unicode escapes before the card paints learner-facing
 * copy. Markdown already does this; ask_user prompts are plain text and used
 * to leak ``\\u300c...`` stems (#973).
 */
function displayText(value: string): string {
  return decodeEscapedUnicodeForDisplay(value);
}

/**
 * One option: v3 emits ``{label, description}`` objects; v2 payloads
 * stored in older sessions carry plain strings. Both normalise to the
 * object shape.
 */
function normaliseOption(raw: unknown): AskUserOption | null {
  if (raw && typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    const label = displayText(String(o.label ?? "").trim());
    if (!label) return null;
    const description =
      typeof o.description === "string" && o.description.trim()
        ? displayText(o.description.trim())
        : null;
    return { label, description };
  }
  const label = displayText(String(raw ?? "").trim());
  return label ? { label, description: null } : null;
}

function normaliseAskUserPayload(
  raw: unknown,
  /**
   * ``allowNoQuestions`` keeps a payload whose questions have not arrived
   * yet. Only a streaming preview passes it: the intro is the first thing
   * the model writes, so honouring it puts the card on screen while the
   * options are still being typed into it. A dispatched call always has at
   * least one question and is rejected without one, as before.
   */
  { allowNoQuestions = false }: { allowNoQuestions?: boolean } = {},
): AskUserPayload | null {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;

  // v2/v3 shape: ``{intro?, questions: [...]}``
  if (Array.isArray(obj.questions)) {
    const questions: AskUserQuestion[] = [];
    for (const item of obj.questions) {
      if (!item || typeof item !== "object") continue;
      const q = item as Record<string, unknown>;
      const prompt = displayText(String(q.prompt ?? q.question ?? "").trim());
      if (!prompt) continue;
      const optionsRaw = Array.isArray(q.options) ? q.options : [];
      questions.push({
        id: String(q.id || `q${questions.length + 1}`),
        prompt,
        header:
          typeof q.header === "string" && q.header.trim()
            ? displayText(q.header.trim())
            : null,
        multi_select: Boolean(q.multi_select ?? q.multiSelect),
        options: optionsRaw
          .map(normaliseOption)
          .filter((o): o is AskUserOption => o !== null),
        allow_free_text: q.allow_free_text === false ? false : true,
        placeholder:
          typeof q.placeholder === "string" && q.placeholder.trim()
            ? displayText((q.placeholder as string).trim())
            : null,
      });
    }
    const intro =
      typeof obj.intro === "string" && obj.intro.trim()
        ? displayText((obj.intro as string).trim())
        : null;
    if (questions.length === 0 && !(allowNoQuestions && intro)) return null;
    return { intro, questions };
  }

  // Legacy single-question shape from before the multi-question refactor.
  const prompt = displayText(String(obj.question ?? "").trim());
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
  /**
   * Deliver the answers. Resolving ``false`` means they never reached a turn
   * that was waiting for them, and the card returns to editable so the
   * learner can try again — a submission that cannot succeed must not look
   * like one still in flight.
   */
  onSubmit: (payload: {
    text?: string;
    answers?: Array<{ questionId: string; text: string }>;
  }) => void | boolean | Promise<void | boolean>;
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
  return (
    <InteractiveAskUserCard
      payload={data.payload}
      onSubmit={onSubmit}
      streaming={data.streaming ?? false}
    />
  );
});
AskUserOptions.displayName = "AskUserOptions";

// ---------- interactive mode ----------

const InteractiveAskUserCard = memo(function InteractiveAskUserCard({
  payload,
  onSubmit,
  streaming = false,
}: {
  payload: AskUserPayload;
  onSubmit: (payload: {
    text?: string;
    answers?: Array<{ questionId: string; text: string }>;
  }) => void | boolean | Promise<void | boolean>;
  /** The model is still writing this card; see ``AskUserCardData``. */
  streaming?: boolean;
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
  // "In flight", not "done": the server may still decline these answers.
  const {
    sending: submitted,
    failed: submitFailed,
    submit,
  } = useCardSubmission(onSubmit);
  // Same lock, two reasons: answers are in flight, or the question is not
  // finished being asked. Either way nothing on the card may be touched.
  const locked = submitted || streaming;

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
    if (locked) return;
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
    void submit({ text: flat, answers: list });
  }, [locked, payload.questions, answers, submit]);

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
          <div
            className={
              "mt-0.5 text-[11px] " +
              (submitFailed
                ? "text-[var(--destructive)]"
                : "text-[var(--muted-foreground)]")
            }
          >
            {streaming
              ? t("Writing the question…")
              : submitted
                ? t("Sending your answers…")
                : submitFailed
                  ? t(REPLY_NOT_DELIVERED)
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
                disabled={locked}
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

      {activeQuestion ? (
        <QuestionBody
          key={activeQuestion.id}
          question={activeQuestion}
          pickedLabels={picks[activeQuestion.id] ?? []}
          customDraft={customText[activeQuestion.id] ?? ""}
          customSelected={!!customSelected[activeQuestion.id]}
          locked={locked}
          onPickOption={(label) => pickOption(activeQuestion, label)}
          onSelectCustom={() => selectCustom(activeQuestion)}
          onCustomTextChange={(text) =>
            updateCustomText(activeQuestion.id, text)
          }
        />
      ) : (
        // A preview that has only its intro so far. Two muted bars stand in
        // for the question and its first option, so the card takes its place
        // in the thread at roughly the height it will settle at instead of
        // pushing the conversation down as each option arrives.
        <div className="mt-3 flex flex-col gap-2" aria-hidden>
          <div className="h-4 w-2/3 animate-pulse rounded bg-[color-mix(in_srgb,var(--foreground)_8%,transparent)]" />
          <div className="h-9 w-full animate-pulse rounded-xl bg-[color-mix(in_srgb,var(--foreground)_5%,transparent)]" />
        </div>
      )}

      <div className="mt-3 flex items-center justify-between gap-2 border-t border-[var(--border)]/60 pt-3">
        <div className="flex min-w-0 flex-1 items-center">
          {totalQuestions > 1 && activeIdx > 0 ? (
            <button
              type="button"
              onClick={() => setActiveIdx((idx) => Math.max(0, idx - 1))}
              disabled={locked}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-transparent px-2.5 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--foreground)]/30 hover:bg-[color-mix(in_srgb,var(--foreground)_4%,transparent)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft size={14} strokeWidth={2} />
              <span>{t("Previous question")}</span>
            </button>
          ) : (
            <div className="text-[11.5px] text-[var(--muted-foreground)]">
              {streaming
                ? null
                : allAnswered
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
            disabled={locked}
            className="inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span>{t("Next question")}</span>
            <ChevronRight size={14} strokeWidth={2} />
          </button>
        ) : (
          <button
            type="button"
            onClick={handleSubmit}
            disabled={locked}
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
