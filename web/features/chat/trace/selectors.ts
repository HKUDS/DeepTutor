import type { StreamEvent } from "@/features/chat/model/protocol";
import { formatProgressLabel, type ToolProvider } from "@/lib/trace-tools";
import type {
  StreamingMode,
  TraceDisplayItem,
  TraceItem,
  TraceMetadata,
} from "./model";

export function getTraceMeta(event: StreamEvent): TraceMetadata {
  return (event.metadata ?? {}) as TraceMetadata;
}

export function getTraceCallKind(events: StreamEvent[]): string {
  for (const event of events) {
    const value = getTraceMeta(event).call_kind;
    if (value) return String(value);
  }
  return "";
}

export function getTraceRole(events: StreamEvent[]): string {
  for (const event of events) {
    const value = getTraceMeta(event).trace_role;
    if (value) return String(value);
  }
  return "";
}

export function getTraceGroup(events: StreamEvent[]): string {
  for (const event of events) {
    const value = getTraceMeta(event).trace_group;
    if (value) return String(value);
  }
  return "";
}

/**
 * The engine a retrieval or search call ran on, if it reported one.
 *
 * Two places to look, because the backend surfaces it two ways: the
 * retrieval pipeline tags its own progress events at the top level, while a
 * tool's `ToolResult.metadata` is nested under `tool_metadata` by
 * `tool_dispatch`. Both are read here so callers do not have to know which
 * kind of row they are holding.
 */
export function getCallProvider(events: StreamEvent[]): string {
  for (const event of events) {
    const meta = getTraceMeta(event);
    const nested = meta.tool_metadata;
    const value =
      (nested && typeof nested.provider === "string" ? nested.provider : "") ||
      meta.provider ||
      "";
    const trimmed = String(value).trim();
    if (trimmed && trimmed !== "none") return trimmed;
  }
  return "";
}

export function getToolProvider(events: StreamEvent[]): ToolProvider | null {
  for (const event of events) {
    const meta = getTraceMeta(event);
    if (meta.tool_source) {
      return {
        source: String(meta.tool_source),
        id: String(meta.tool_provider || ""),
      };
    }
  }
  return null;
}

export function getLatestToolProgress(events: StreamEvent[]): string {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (
      event.type === "progress" &&
      getTraceMeta(event).trace_kind === "tool_progress" &&
      event.content.trim()
    ) {
      return formatProgressLabel(event.content.trim());
    }
  }
  return "";
}

export function isTracePending(events: StreamEvent[]): boolean {
  let running = false;
  let terminal = false;
  for (const event of events) {
    const state = String(getTraceMeta(event).call_state || "");
    if (state === "running") running = true;
    if (state === "complete" || state === "error") terminal = true;
  }
  return running && !terminal;
}

export function groupTraceEvents(events: StreamEvent[]): TraceItem[] {
  const groups = new Map<string, StreamEvent[]>();
  for (const event of events) {
    const callId = String(getTraceMeta(event).call_id || "");
    if (!callId) continue;
    const group = groups.get(callId);
    if (group) group.push(event);
    else groups.set(callId, [event]);
  }
  return [...groups].map(([callId, groupedEvents]) => ({
    callId,
    events: groupedEvents,
  }));
}

export function isChatLoopAnswerContent(event: StreamEvent): boolean {
  return (
    event.type === "content" &&
    getTraceMeta(event).call_kind === "agent_loop_round"
  );
}

/**
 * Whether this group's own text was taken back out of the answer. Only then
 * is a chat-loop round's prose trace material — ordinary commentary stays in
 * the bubble where the reader watched it arrive.
 */
export function isRetractedRound(events: StreamEvent[]): boolean {
  return events.some((event) => {
    const meta = getTraceMeta(event);
    return (
      meta.trace_kind === "call_status" &&
      meta.call_state === "complete" &&
      meta.answer_visible === false
    );
  });
}

export function groupHasTraceSubstance(events: StreamEvent[]): boolean {
  const retracted = isRetractedRound(events);
  return events.some((event) => {
    if (
      event.type === "tool_call" ||
      event.type === "tool_result" ||
      event.type === "error"
    ) {
      return true;
    }
    if (event.type === "thinking" || event.type === "observation") {
      return Boolean(event.content.trim());
    }
    if (event.type === "progress") {
      return (
        getTraceMeta(event).trace_kind !== "call_status" &&
        Boolean(event.content.trim())
      );
    }
    if (event.type === "content") {
      return (
        (retracted || !isChatLoopAnswerContent(event)) &&
        Boolean(event.content.trim())
      );
    }
    return false;
  });
}

/**
 * Has a round completed as the turn's terminal one?
 *
 * The chat loop's rounds all stream text, so "text is flowing" says nothing
 * about whether the turn is winding up. The round's own completion marker
 * does: ``finish`` is emitted only by a round that called no tools, which is
 * the one shape that ends the loop.
 *
 * Reads only the LATEST completed round, not "has one ever appeared" — a
 * token-truncated round is explicitly non-terminal, so once its own next round
 * completes, that marker supersedes this one.
 *
 * ``answer_visible`` is deliberately not consulted: it says whether a round's
 * text belongs to the answer, which is true of nearly every round and says
 * nothing about whether the turn is over.
 */
export function hasSettledFinalRound(events: StreamEvent[]): boolean {
  for (let idx = events.length - 1; idx >= 0; idx -= 1) {
    const meta = getTraceMeta(events[idx]);
    if (meta.trace_kind === "call_status" && meta.call_state === "complete") {
      return meta.call_role === "finish";
    }
  }
  return false;
}

export function selectTraceDisplayItems(
  traceGroups: TraceItem[],
): TraceDisplayItem[] {
  const items: TraceDisplayItem[] = [];
  let currentStep: string | null = null;
  let stepTraces: TraceItem[] = [];
  const flush = () => {
    if (currentStep !== null && stepTraces.length) {
      items.push({ kind: "step", stepId: currentStep, traces: stepTraces });
    }
    currentStep = null;
    stepTraces = [];
  };

  for (const group of traceGroups) {
    const meta = getTraceMeta(group.events[0]);
    const groupType = getTraceGroup(group.events);
    const stepId = meta.step_id ? String(meta.step_id) : "";
    const kind = getTraceCallKind(group.events);
    if (kind === "llm_final_response") continue;
    if (
      group.events.some(
        (event) => getTraceMeta(event).absorbed_into_final === true,
      )
    )
      continue;
    if (!groupHasTraceSubstance(group.events)) continue;

    if (groupType === "react_round" && stepId) {
      if (currentStep === stepId) stepTraces.push(group);
      else {
        flush();
        currentStep = stepId;
        stepTraces = [group];
      }
    } else if (currentStep !== null && kind !== "llm_generation") {
      stepTraces.push(group);
    } else {
      flush();
      items.push({ kind: "trace", trace: group });
    }
  }
  flush();
  return items;
}

export function hasRenderableCallTrace(events: StreamEvent[]): boolean {
  return selectTraceDisplayItems(groupTraceEvents(events)).length > 0;
}

export function detectStreamingMode(
  events: StreamEvent[],
  hasFinalContent: boolean,
  isStreaming: boolean,
): StreamingMode {
  if (!isStreaming) return "responded";
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    const kind = getTraceMeta(event).call_kind || "";
    if (event.type === "tool_call") {
      if (event.stage === "exploring") return "exploring";
      if (event.stage === "quizzing") return "quizzing";
      return "tool_using";
    }
    if (event.type === "tool_result") continue;
    if (kind === "agent_loop_round") {
      return event.type === "content" ? "responding" : "exploring";
    }
    if (kind === "quiz_question_emitted") return "quizzing";
    if (kind === "tool_result_reflection") return "reflecting";
    if (event.type === "content" && kind === "llm_final_response") {
      if (event.stage === "exploring") return "exploring";
      return "responding";
    }
    if (kind === "llm_planning") return "planning";
    if (event.type === "thinking" && kind === "llm_reasoning") {
      if (event.stage === "exploring") return "exploring";
      if (event.stage === "quizzing") return "quizzing";
      return "reasoning";
    }
  }
  return hasFinalContent ? "responding" : "reasoning";
}
