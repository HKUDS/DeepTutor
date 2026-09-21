"use client";

import { ChevronDown, ChevronLeft, ChevronRight, Pencil } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import InlineMarkdown from "@/components/common/InlineMarkdown";
import { useCardSubmission } from "@/hooks/use-card-submission";
import { REPLY_NOT_DELIVERED } from "@/lib/ask-user-state";
import { decodeEscapedUnicodeForDisplay } from "@/lib/markdown-display";
import {
  readPosedQuestion,
  type MasteryQuestion,
} from "@/lib/mastery-question";
import {
  collectRetractedCallIds,
  shouldAppendEventContent,
} from "@/lib/stream";
import { hasRenderableCallTrace } from "@/features/chat/trace/selectors";
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
   * One run of work — tool calls, their results, the reasoning around them —
   * rendered exactly where it happened, between the text that introduced it
   * and the text that followed. This is what makes the message read like a
   * terminal agent: say what you are about to do, do it, say what came of it.
   *
   * A region opens as soon as trace events arrive after some answer text, and
   * closes when the next text run starts.
   */
  | { kind: "trace"; events: StreamEvent[]; key: string };

/** Every id this event answers to, for matching a row against its call. */
function callIdsOf(event: StreamEvent): string[] {
  const meta = (event.metadata ?? {}) as Record<string, unknown>;
  return [
    (event as { tool_call_id?: string }).tool_call_id,
    typeof meta.tool_call_id === "string" ? meta.tool_call_id : undefined,
    typeof meta.call_id === "string" ? meta.call_id : undefined,
  ].filter((id): id is string => Boolean(id));
}

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
  let seq = 0;
  // A round a capability rejected was streamed and then taken back: its text
  // is trace material, never answer text. Ordinary commentary stays.
  const retractedCallIds = collectRetractedCallIds(events);
  // Calls the reader sees as a card. Their *payloads* are not trace material
  // — the card is what those say. The call itself is: stopping to ask is a
  // step the agent took, and a trace with no row for it claims the answers
  // appeared out of nowhere. So the ``tool_call`` row stays and everything
  // else about a card's call (its result payload, its draft previews) is
  // dropped, leaving the row above the card it opened.
  // Both id fields are collected because the two sides name the call
  // differently: a dispatched result carries ``tool_call_id`` while the trace
  // groups rows by ``call_id``, and which one a given event has depends on the
  // provider.
  const cardCallIds = new Set<string>();
  for (const event of events) {
    if (!producesCard(event)) continue;
    for (const id of callIdsOf(event)) cardCallIds.add(id);
  }

  const ensureTextSegment = () => {
    // Text resuming closes the run of work above it, so the next tool call
    // opens a region of its own below this paragraph rather than joining the
    // one the reader has already scrolled past.
    pendingTraceIdx = null;
    if (pendingTextIdx === null) {
      pendingTextIdx = segments.length;
      segments.push({ kind: "text", text: "", key: `t${seq++}` });
    }
    return pendingTextIdx;
  };

  /** Collect one trace event into the region currently open below the text. */
  const appendTraceEvent = (event: StreamEvent) => {
    if (producesCard(event)) return;
    if (
      event.type !== "tool_call" &&
      callIdsOf(event).some((id) => cardCallIds.has(id))
    ) {
      return;
    }
    // Where this event sat in the answer, when it recorded one. A live turn
    // records none — its text is on the wire and separates the regions by
    // itself. A reloaded one has no text events at all, so this mark is the
    // only thing that still says which paragraph a row belonged under.
    const raw = ((event.metadata ?? {}) as Record<string, unknown>)
      .assistant_content_offset;
    const offset = typeof raw === "number" ? raw : null;
    if (pendingTraceIdx !== null && offset !== null) {
      const open = answerOffsets.get(pendingTraceIdx);
      // Two calls made at different points in the answer are two runs of work
      // with prose between them, even though the preview dropped that prose.
      // Without this they collapsed into one block and the reloaded turn
      // stopped resembling the one the reader had watched.
      if (open !== undefined && open !== offset) pendingTraceIdx = null;
    }
    if (pendingTraceIdx === null) {
      // Work starting closes the paragraph above it, so what the next round
      // writes lands in a new run *below* this region rather than being
      // appended to text the reader has already passed.
      pendingTextIdx = null;
      pendingTraceIdx = segments.length;
      segments.push({ kind: "trace", events: [], key: `r${seq++}` });
    }
    const seg = segments[pendingTraceIdx];
    if (seg.kind === "trace") seg.events.push(event);
    // Read from the first event in the region that recorded a mark — a region
    // often opens on a status marker, which carries none.
    if (offset !== null && !answerOffsets.has(pendingTraceIdx)) {
      answerOffsets.set(pendingTraceIdx, offset);
    }
  };

  for (const event of events) {
    if (shouldAppendEventContent(event)) {
      const callId = ((event.metadata ?? {}) as { call_id?: string }).call_id;
      if (callId && retractedCallIds.has(callId)) {
        appendTraceEvent(event);
        continue;
      }
      // Keep the transition to answer text with the preceding reasoning
      // trace so it can fold before the whole model call finishes. Only the
      // first delta is needed; subsequent answer deltas stay in the text.
      if (pendingTraceIdx !== null && callId) {
        const trace = segments[pendingTraceIdx];
        if (
          trace.kind === "trace" &&
          trace.events.some(
            (entry) =>
              entry.type === "thinking" && entry.metadata?.call_id === callId,
          )
        ) {
          trace.events.push(event);
        }
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
        // Same bookkeeping as a card below: close the text and trace runs so
        // the round's remaining prose starts fresh underneath the card.
        pendingTextIdx = null;
        pendingTraceIdx = null;
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
      // Deliberately leaving the trace region open: the events that belong to
      // this very call are still ahead of us in the stream, and they read as
      // the work that produced the question — above it, not below.
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

  // Two kinds of segment are dropped before the body is laid out around what
  // remains, because a segment removed afterwards would leave the text it had
  // split sitting in two paragraphs with nothing between them:
  //
  //  - a region holding nothing worth a row. Regions open on a round's status
  //    marker, which on its own is bookkeeping, not something to show;
  //  - once the turn has settled, a preview still marked streaming. It never
  //    became a dispatched call (a duplicate parallel ask_user, a guard that
  //    rejected the arguments), so there is nothing behind it to answer.
  //
  // Dropping either shifts the indices ``answerOffsets`` is keyed by, so the
  // offsets are rebuilt alongside.
  const kept: MessageSegment[] = [];
  const keptOffsets = new Map<number, number>();
  segments.forEach((segment, idx) => {
    if (segment.kind === "trace" && !hasRenderableCallTrace(segment.events)) {
      return;
    }
    if (!streaming && segment.kind === "ask_user" && segment.data.streaming) {
      return;
    }
    const offset = answerOffsets.get(idx);
    if (offset !== undefined) keptOffsets.set(kept.length, offset);
    kept.push(segment);
  });

  // A live turn carries its own text on the wire. A settled one is restored
  // from an event preview that drops `content` entirely, so its body has to be
  // rebuilt from the persisted answer and laid out around the rows.
  const textFromEvents = kept.some(
    (s) => s.kind === "text" && s.text.length > 0,
  );
  const laidOut =
    !textFromEvents && answerContent
      ? layOutAnswerContent(kept, answerContent, keptOffsets)
      : kept;

  // Empty text segments last: the layout above creates them, and a blank one
  // would render as an empty ``<AssistantResponse>``.
  return laidOut.filter((s) => s.kind !== "text" || s.text.length > 0);
}

/**
 * Lay the persisted answer out around the rows of a settled message.
 *
 * A reloaded turn has no `content` events — the event preview drops them — so
 * the body is one stored string and every card and run of tool work has to be
 * put back where it happened. Each row takes the text between the previous cut
 * and its own recorded offset; the text past the last cut trails after
 * everything. Offsets are read in order and never move backwards, so a stray
 * value cannot reorder the body.
 *
 * A row with no recorded offset is placed differently by kind. A card is a
 * question the reader was asked, so it belongs below everything written before
 * it. A run of tool work is not worth pushing the whole answer above, so it
 * simply keeps its position in the sequence.
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
    const offset = answerOffsets.get(idx);
    if (offset !== undefined) {
      pushText(snapToLineStart(answerContent, Math.max(cursor, offset)));
    } else if (segment.kind !== "trace") {
      pushText(answerContent.length);
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
 * Whether this event is what a card is built from, rather than trace material.
 *
 * A card renders in the message body, so the row its own events would draw in
 * the activity block is the same step shown twice — as a question the reader
 * can answer, and as a bare "tool call" line above the text that introduced
 * it.
 */
function producesCard(event: StreamEvent): boolean {
  const meta = (event.metadata ?? {}) as Record<string, unknown>;
  if (event.type === "progress") {
    return Boolean(meta.ask_user_resolved) || readAskUserDraft(event) !== null;
  }
  if (event.type !== "tool_result") return false;
  if (readPosedQuestion(event)) return true;
  const toolMetadata = meta.tool_metadata;
  const askUser =
    toolMetadata && typeof toolMetadata === "object"
      ? (toolMetadata as Record<string, unknown>).ask_user
      : null;
  return normaliseAskUserPayload(askUser) !== null;
}

/**
 * The events whose trace rows still belong to the message's top activity
 * block — which, now that every row renders inline where the work happened,
 * should be nothing at all. Kept as the honest statement of that: anything it
 * returns is a step the body did not account for.
 *
 * Pass it as ``AssistantActivity``'s ``traceEvents`` (or to a bare
 * ``TraceFlow``) so no step is shown twice.
 */
export function leadingTraceEvents(
  events: StreamEvent[] | undefined,
  segments: MessageSegment[],
): StreamEvent[] {
  const claimed = new Set<StreamEvent>();
  for (const event of events ?? []) {
    if (producesCard(event)) claimed.add(event);
  }
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

/**
 * Render the ``ask_user`` card.
 *
 * Both visual modes are drawn on the same shell — same radius, border and
 * padding — so answering does not swap one panel for another: the question
 * fades to muted, the answer takes its place, and the card keeps its spot in
 * the message stream. Switches from ``interactive`` (the agent is still
 * paused) to ``resolved`` (the user has submitted) once a ``progress`` event
 * with ``ask_user_resolved=true`` arrives in the message events.
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
   * the user can hide / show the question + answer summary. Off by default:
   * an answered exchange is two short lines, so folding it away costs more
   * than it saves. Research turns it on to clear the bubble for the outline
   * editor once the outline takes over. */
  collapsible?: boolean;
  /** Only honoured when ``collapsible`` is true. */
  defaultCollapsed?: boolean;
}) {
  if (data.resolved) {
    return (
      <ResolvedAskUserCard
        payload={data.payload}
        answers={data.answers ?? []}
        collapsible={collapsible ?? false}
        defaultCollapsed={defaultCollapsed ?? false}
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

  /**
   * Send one specific answer table, rather than whatever ``answers`` holds.
   *
   * A skip clears the current question and submits in the same click, and
   * ``setState`` has not landed by then — so the caller passes the table it
   * means, and "skipped" cannot go out carrying the pick it just cleared.
   */
  const submitAnswers = useCallback(
    (finalAnswers: Record<string, string>) => {
      const list: Array<{ questionId: string; text: string }> =
        payload.questions.map((q) => ({
          questionId: q.id,
          text: (finalAnswers[q.id] ?? "").trim(),
        }));
      // Always include a flat ``text`` synopsis for back-compat with any
      // older server path that only looks at ``text``.
      const flat = list
        .map(({ text }) => text)
        .filter(Boolean)
        .join(" | ");
      void submit({ text: flat, answers: list });
    },
    [payload.questions, submit],
  );

  const handleSubmit = useCallback(() => {
    if (locked) return;
    submitAnswers(answers);
  }, [locked, answers, submitAnswers]);

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

  /**
   * Decline the question on screen.
   *
   * On a multi-question card this means "not this one" — move on to whatever
   * is still unanswered. On the last (or only) question there is nothing left
   * to move to, so declining submits the card with this answer left empty,
   * which the backend renders back to the model as ``(skipped)``.
   */
  const skipQuestion = useCallback(() => {
    if (locked || !activeQuestion) return;
    const qid = activeQuestion.id;
    setPicks((prev) => ({ ...prev, [qid]: [] }));
    setCustomSelected((prev) => ({ ...prev, [qid]: false }));
    // Skip only ever walks forward. Wrapping round to a question the user
    // has already declined would bounce the card between two skipped
    // questions with no way out; reaching the end means there is nothing
    // left to ask, so the card submits and the unanswered ones go as
    // skipped.
    for (let j = activeIdx + 1; j < totalQuestions; j++) {
      if (!(answers[payload.questions[j].id] ?? "").trim()) {
        setActiveIdx(j);
        return;
      }
    }
    submitAnswers({ ...answers, [qid]: "" });
  }, [
    locked,
    activeQuestion,
    totalQuestions,
    activeIdx,
    payload.questions,
    answers,
    submitAnswers,
  ]);

  /**
   * Number keys pick the option carrying that number — what the badges are
   * advertising by being numbered at all.
   *
   * Bound on ``window`` because the card is never the focused element (the
   * composer usually is), so anything typed into a field, and anything with a
   * modifier, belongs to whatever has focus and is left alone.
   */
  useEffect(() => {
    if (locked || !activeQuestion || activeQuestion.options.length === 0) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.isContentEditable ||
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT")
      ) {
        return;
      }
      const picked = Number(event.key);
      if (
        !Number.isInteger(picked) ||
        picked < 1 ||
        picked > activeQuestion.options.length
      ) {
        return;
      }
      event.preventDefault();
      pickOption(activeQuestion, activeQuestion.options[picked - 1].label);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [locked, activeQuestion, pickOption]);

  // The question itself is the card's headline — no icon, no standing
  // instruction row. The status line below the intro only appears when there
  // is something to say that the card's own shape does not already say
  // (still being written, in flight, refused).
  const status = streaming
    ? t("Writing the question…")
    : submitted
      ? t("Sending your answers…")
      : submitFailed
        ? t(REPLY_NOT_DELIVERED)
        : null;

  return (
    <div className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3.5 py-3 shadow-[0_1px_2px_rgba(0,0,0,0.04),0_4px_14px_rgba(0,0,0,0.04)]">
      {payload.intro || totalQuestions === 0 ? (
        <div className="text-[12.5px] leading-snug text-[var(--muted-foreground)]">
          {payload.intro ? (
            <InlineMarkdown content={payload.intro} />
          ) : (
            t("Please answer to continue.")
          )}
        </div>
      ) : null}
      {status ? (
        <div
          className={
            "mt-0.5 text-[11px] " +
            (submitFailed
              ? "text-[var(--destructive)]"
              : "text-[var(--muted-foreground)]")
          }
        >
          {status}
        </div>
      ) : null}

      {totalQuestions > 1 ? (
        <div className="mt-2 flex flex-wrap gap-1">
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
                  "flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium transition-all " +
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
          spaced={
            Boolean(payload.intro) || status !== null || totalQuestions > 1
          }
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
        <div className="mt-2 flex flex-col gap-1.5" aria-hidden>
          <div className="h-4 w-2/3 animate-pulse rounded bg-[color-mix(in_srgb,var(--foreground)_8%,transparent)]" />
          <div className="h-9 w-full animate-pulse rounded-xl bg-[color-mix(in_srgb,var(--foreground)_5%,transparent)]" />
        </div>
      )}

      <div className="mt-2 flex items-center justify-between gap-2 border-t border-[var(--border)]/60 pt-2">
        <div className="flex min-w-0 flex-1 items-center">
          {totalQuestions > 1 && activeIdx > 0 ? (
            <button
              type="button"
              onClick={() => setActiveIdx((idx) => Math.max(0, idx - 1))}
              disabled={locked}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-transparent px-2 py-1 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--foreground)]/30 hover:bg-[color-mix(in_srgb,var(--foreground)_4%,transparent)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft size={14} strokeWidth={2} />
              <span>{t("Previous question")}</span>
            </button>
          ) : (
            <div className="text-[11.5px] text-[var(--muted-foreground)]">
              {/* Only a multi-question card needs telling how its parts add
                  up; a single question says it with the Skip control alone. */}
              {streaming || totalQuestions < 2
                ? null
                : allAnswered
                  ? t("All questions answered.")
                  : t("Unanswered questions will be submitted as skipped.")}
            </div>
          )}
        </div>
        {/* Declining and answering are the same kind of act — both end this
            question — so Skip belongs beside Submit rather than in a band of
            its own above it. */}
        <div className="flex shrink-0 items-center gap-1.5">
          {activeQuestion ? (
            <button
              type="button"
              onClick={skipQuestion}
              disabled={locked}
              className="rounded-md border border-[var(--border)] px-2 py-1 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--foreground)]/30 hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {t("Skip")}
            </button>
          ) : null}
          {totalQuestions > 1 && activeIdx < totalQuestions - 1 ? (
            <button
              type="button"
              onClick={() =>
                setActiveIdx((idx) => Math.min(totalQuestions - 1, idx + 1))
              }
              disabled={locked}
              className="inline-flex items-center gap-1 rounded-md bg-[var(--primary)] px-2.5 py-1 text-[12px] font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <span>{t("Next question")}</span>
              <ChevronRight size={14} strokeWidth={2} />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={locked}
              className="rounded-md bg-[var(--primary)] px-2.5 py-1 text-[12px] font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {totalQuestions > 1 ? t("Submit answers") : t("Submit")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
});
InteractiveAskUserCard.displayName = "InteractiveAskUserCard";

/**
 * One question: its prompt, its options, the free-text row and Skip.
 *
 * Options are rows, not boxes. Nesting a bordered control per option inside a
 * bordered card reads as a form to fill in; a numbered row that lights up
 * under the cursor reads as a list to pick from — the rule the mastery card
 * already set for itself (see ``MasteryQuestionCard``). The number is not
 * decoration: it is the key that picks that row.
 */
const QuestionBody = memo(function QuestionBody({
  question,
  pickedLabels,
  customDraft,
  customSelected,
  locked,
  spaced,
  onPickOption,
  onSelectCustom,
  onCustomTextChange,
}: {
  question: AskUserQuestion;
  pickedLabels: string[];
  customDraft: string;
  customSelected: boolean;
  locked: boolean;
  /** Something is rendered above (intro, status, tabs) and needs clearing. */
  spaced: boolean;
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
      <div
        className={
          (spaced ? "mt-1.5 " : "") +
          "text-[15px] font-medium leading-snug text-[var(--foreground)]"
        }
      >
        <InlineMarkdown content={question.prompt} />
        {question.multi_select ? (
          <span className="ml-1.5 text-[11px] font-normal text-[var(--muted-foreground)]">
            {t("Select all that apply.")}
          </span>
        ) : null}
      </div>

      {question.options.length > 0 ? (
        <div className="mt-1.5 flex flex-col">
          {question.options.map((option, idx) => {
            const isPicked = question.multi_select
              ? pickedLabels.includes(option.label)
              : !customSelected && pickedLabels[0] === option.label;
            return (
              <button
                key={`${idx}-${option.label}`}
                type="button"
                onClick={() => !locked && onPickOption(option.label)}
                disabled={locked}
                aria-pressed={isPicked}
                className={
                  "group -mx-1.5 flex w-[calc(100%+0.75rem)] items-start gap-2.5 rounded-lg px-1.5 py-1 text-left transition-colors " +
                  (isPicked
                    ? "bg-[color-mix(in_srgb,var(--foreground)_6%,transparent)]"
                    : locked
                      ? ""
                      : "hover:bg-[color-mix(in_srgb,var(--foreground)_3.5%,transparent)]") +
                  " disabled:cursor-not-allowed disabled:opacity-60"
                }
              >
                <span
                  className={
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[12px] font-semibold tabular-nums transition-colors " +
                    (isPicked
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "bg-[color-mix(in_srgb,var(--foreground)_6%,transparent)] text-[var(--muted-foreground)] group-hover:text-[var(--foreground)]")
                  }
                >
                  {question.multi_select && isPicked ? "✓" : idx + 1}
                </span>
                <span className="min-w-0 flex-1 pt-0.5">
                  <span className="block text-[14px] font-medium leading-snug text-[var(--foreground)]">
                    <InlineMarkdown content={option.label} />
                  </span>
                  {option.description ? (
                    <span className="mt-0.5 block text-[12.5px] leading-snug text-[var(--muted-foreground)]">
                      <InlineMarkdown content={option.description} />
                    </span>
                  ) : null}
                </span>
              </button>
            );
          })}
        </div>
      ) : null}

      {/* Saying it yourself is one more way to answer, so it reads as the last
          row of the list — same badge slot, same hover — instead of sitting in
          a band of its own behind a second rule. */}
      {question.allow_free_text ? (
        <div className={question.options.length > 0 ? "" : "mt-1.5"}>
          {customSelected ? (
            <div className="flex min-w-0 items-start gap-2.5 px-0 py-1">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--primary)] text-[var(--primary-foreground)]">
                <Pencil size={13} strokeWidth={2} />
              </span>
              <textarea
                ref={textareaRef}
                value={customDraft}
                onChange={(event) => onCustomTextChange(event.target.value)}
                placeholder={question.placeholder ?? t("Type your reply…")}
                rows={2}
                disabled={locked}
                className="min-h-[1.5rem] w-full resize-y bg-transparent pt-0.5 text-[14px] leading-snug text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/80 disabled:opacity-60"
              />
            </div>
          ) : (
            <button
              type="button"
              onClick={() => !locked && onSelectCustom()}
              disabled={locked}
              className="group -mx-1.5 flex w-[calc(100%+0.75rem)] items-center gap-2.5 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-[color-mix(in_srgb,var(--foreground)_3.5%,transparent)] disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[color-mix(in_srgb,var(--foreground)_6%,transparent)] text-[var(--muted-foreground)] group-hover:text-[var(--foreground)]">
                <Pencil size={13} strokeWidth={2} />
              </span>
              <span className="truncate text-[14px] text-[var(--muted-foreground)] group-hover:text-[var(--foreground)]">
                {customDraft.trim()
                  ? t("Other: {{text}}", { text: customDraft.trim() })
                  : t("Something else…")}
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

  // Same shell as the question it replaces (see ``AskUserOptions``): the
  // prompt drops to muted, the answer holds the foreground, and nothing else
  // is added — an answered exchange is history, not a panel. ``collapsible``
  // is research's alone: it needs the bubble back for the outline editor, so
  // there the card keeps a header row to fold from.
  return (
    <div
      data-testid="ask-user-answers"
      className="mt-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3.5 py-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.04),0_4px_14px_rgba(0,0,0,0.04)]"
    >
      {collapsible ? (
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-expanded={!collapsed}
          className={`-mx-1.5 flex w-[calc(100%+0.75rem)] items-center gap-1.5 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-[color-mix(in_srgb,var(--foreground)_3.5%,transparent)] ${
            collapsed ? "" : "mb-2"
          }`}
        >
          <ChevronDown
            size={12}
            className={`shrink-0 text-[var(--muted-foreground)]/50 transition-transform ${
              collapsed ? "-rotate-90" : ""
            }`}
          />
          <span className="text-[12.5px] font-medium text-[var(--muted-foreground)]">
            {t("Your answers")}
          </span>
          {collapsed && (
            <span className="text-[11px] text-[var(--muted-foreground)]/45">
              · {answeredCount}/{payload.questions.length} {t("answered")}
            </span>
          )}
        </button>
      ) : null}
      {!collapsed && (
        <div className="space-y-2">
          {payload.questions.map((q) => {
            const value = (byId.get(q.id) ?? "").trim();
            return (
              <div key={q.id} className="space-y-0.5">
                <div className="text-[12.5px] leading-snug text-[var(--muted-foreground)]">
                  <InlineMarkdown content={q.prompt} />
                </div>
                <div className="text-[14px] font-medium leading-snug text-[var(--foreground)]">
                  {value ? (
                    <InlineMarkdown content={value} />
                  ) : (
                    <span className="font-normal italic text-[var(--muted-foreground)]/70">
                      {t("(skipped)")}
                    </span>
                  )}
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
