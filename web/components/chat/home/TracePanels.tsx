"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BrainCircuit,
  ChevronDown,
  Database,
  Loader2,
  MessageSquare,
  PenLine,
  Sparkles,
  Terminal,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import type { StreamEvent } from "@/lib/unified-ws";

type TraceMetadata = {
  call_id?: string;
  phase?: string;
  label?: string;
  call_kind?: string;
  trace_role?: string;
  trace_group?: string;
  trace_kind?: string;
  trace_id?: string;
  call_state?: string;
  step_id?: string;
  round?: number;
  query?: string;
  tool_name?: string;
  trace_layer?: string;
  output_mode?: string;
  quality?: string;
  sources?: Array<Record<string, unknown>>;
};

type ResearchStageCard = {
  id: "understand" | "decompose" | "evidence" | "result";
  title: string;
  hint: string;
  events: StreamEvent[];
};

const RESEARCH_STAGE_SPECS: Array<Pick<ResearchStageCard, "id" | "title" | "hint">> = [
  { id: "understand", title: "Understand the Problem", hint: "Clarify topic and research goals first." },
  { id: "decompose", title: "Decompose Topic", hint: "Break the topic into searchable and learnable subtopics." },
  { id: "evidence", title: "Gather Evidence", hint: "Collect and organize evidence from selected sources." },
  { id: "result", title: "Produce Result", hint: "Synthesize evidence into the final output." },
];

type TraceItem = { callId: string; events: StreamEvent[] };
type DisplayItem =
  | { kind: "trace"; trace: TraceItem }
  | { kind: "step"; stepId: string; traces: TraceItem[] };

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function titleCase(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function humanizeQuestionId(value: string) {
  return value.replace(/\bq_(\d+)\b/gi, "Question $1");
}

export function getTraceMeta(event: StreamEvent): TraceMetadata {
  return (event.metadata ?? {}) as TraceMetadata;
}

function getTraceLabel(events: StreamEvent[]) {
  for (const event of events) {
    const meta = getTraceMeta(event);
    if (meta.label) return humanizeQuestionId(String(meta.label));
  }
  const fallback = events[0]?.stage || "trace";
  return humanizeQuestionId(titleCase(fallback));
}

function getTraceCallKind(events: StreamEvent[]) {
  for (const event of events) {
    const meta = getTraceMeta(event);
    if (meta.call_kind) return String(meta.call_kind);
  }
  return "";
}

function getTraceRole(events: StreamEvent[]) {
  for (const event of events) {
    const meta = getTraceMeta(event);
    if (meta.trace_role) return String(meta.trace_role);
  }
  return "";
}

function getTraceGroup(events: StreamEvent[]) {
  for (const event of events) {
    const meta = getTraceMeta(event);
    if (meta.trace_group) return String(meta.trace_group);
  }
  return "";
}

function getTraceDurationLabel(events: StreamEvent[]) {
  let start: number | null = null;
  let end: number | null = null;
  for (const event of events) {
    const state = String(getTraceMeta(event).call_state || "");
    if (state === "running" && start === null) start = event.timestamp;
    if ((state === "complete" || state === "error") && end === null) end = event.timestamp;
  }
  if (start === null || end === null) return "";
  const seconds = Math.max(1, Math.round(end - start));
  return `${seconds}s`;
}

function getTraceStartTimestamp(events: StreamEvent[]) {
  for (const event of events) {
    const state = String(getTraceMeta(event).call_state || "");
    if (state === "running") return event.timestamp;
  }
  return null;
}

function getActiveTraceDurationSeconds(events: StreamEvent[], nowSeconds: number) {
  const start = getTraceStartTimestamp(events);
  if (start === null) return null;
  return Math.max(1, Math.round(nowSeconds - start));
}

function isTracePending(events: StreamEvent[]) {
  let hasRunning = false;
  let hasTerminal = false;
  for (const event of events) {
    const state = String(getTraceMeta(event).call_state || "");
    if (state === "running") hasRunning = true;
    if (state === "complete" || state === "error") hasTerminal = true;
  }
  return hasRunning && !hasTerminal;
}

function getTraceHeader(events: StreamEvent[], nowSeconds?: number, nested?: boolean) {
  const label = getTraceLabel(events);
  const role = getTraceRole(events);
  const group = getTraceGroup(events);
  const kind = getTraceCallKind(events);
  const meta = getTraceMeta(events[0]);
  const duration =
    kind === "math_render_output" && isTracePending(events) && nowSeconds
      ? `${getActiveTraceDurationSeconds(events, nowSeconds) ?? 1}s`
      : getTraceDurationLabel(events);

  let title = label;
  if (
    [
      "math_concept_analysis",
      "math_concept_design",
      "math_code_generation",
      "math_code_retry",
      "math_summary",
      "math_render_output",
    ].includes(kind)
  ) {
    title = label;
  } else if (role === "retrieve") {
    title = "Retrieve";
  } else if (kind === "tool_planning") {
    title = "Tool call";
  } else if (group === "react_round") {
    if (nested) {
      title = meta.round ? `Round ${meta.round}` : label;
    } else {
      const step = meta.step_id ? `Step ${meta.step_id}` : "";
      const round = meta.round ? `Round ${meta.round}` : label;
      title = [step, round].filter(Boolean).join(" · ");
    }
  } else if (role === "plan" && kind === "llm_planning") {
    title = "Plan";
  } else if (role === "observe" || kind === "llm_observation") {
    title = "Observe";
  } else if (role === "response" || kind === "llm_final_response") {
    title = "Response";
  } else if (role === "thought" || kind === "llm_reasoning") {
    title = "Thought";
  } else if (kind === "llm_generation") {
    if (/^generate\s+/i.test(label)) title = label.replace(/^generate\s+/i, "Generating ");
    else if (/^write\s+/i.test(label)) title = label.replace(/^write\s+/i, "Writing ");
  }

  return duration ? `${title} for ${duration}` : title;
}

function getTraceText(events: StreamEvent[], eventTypes: Array<StreamEvent["type"]>) {
  const textEvents = events.filter((event) => eventTypes.includes(event.type) && event.content.trim().length > 0);
  if (!textEvents.length) return "";

  const explicitOutputs = textEvents.filter(
    (event) => String(getTraceMeta(event).trace_kind || "") === "llm_output",
  );
  if (explicitOutputs.length > 0) {
    return explicitOutputs[explicitOutputs.length - 1].content;
  }

  return textEvents.map((event) => event.content).join("");
}

function formatTraceArgs(args: unknown) {
  if (args == null) return "";
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

/* ------------------------------------------------------------------ */
/*  Display-item grouping (step-level)                                 */
/* ------------------------------------------------------------------ */

function buildDisplayItems(traceGroups: TraceItem[]): DisplayItem[] {
  const items: DisplayItem[] = [];
  let stepId_: string | null = null;
  let stepTraces: TraceItem[] = [];

  function flushStep() {
    if (stepId_ !== null && stepTraces.length > 0) {
      items.push({ kind: "step", stepId: stepId_, traces: stepTraces });
    }
    stepId_ = null;
    stepTraces = [];
  }

  for (const group of traceGroups) {
    const meta = getTraceMeta(group.events[0]);
    const groupType = getTraceGroup(group.events);
    const stepId = meta.step_id ? String(meta.step_id) : "";
    const kind = getTraceCallKind(group.events);

    if (kind === "llm_final_response") continue;

    if (groupType === "react_round" && stepId) {
      if (stepId_ === stepId) {
        stepTraces.push(group);
      } else {
        flushStep();
        stepId_ = stepId;
        stepTraces = [group];
      }
    } else if (stepId_ !== null && kind !== "llm_generation") {
      stepTraces.push(group);
    } else {
      flushStep();
      items.push({ kind: "trace", trace: group });
    }
  }
  flushStep();
  return items;
}

function getStepGroupDuration(traces: TraceItem[]): string {
  let start: number | null = null;
  let end: number | null = null;
  for (const trace of traces) {
    for (const event of trace.events) {
      const state = String(getTraceMeta(event).call_state || "");
      if (state === "running" && (start === null || event.timestamp < start))
        start = event.timestamp;
      if (
        (state === "complete" || state === "error") &&
        (end === null || event.timestamp > end)
      )
        end = event.timestamp;
    }
  }
  if (start === null || end === null) return "";
  return `${Math.max(1, Math.round(end - start))}s`;
}

/* ------------------------------------------------------------------ */
/*  Primitive UI pieces                                                */
/* ------------------------------------------------------------------ */

function ScrollableTraceBody({
  children,
  autoScroll,
  className = "ml-5 mr-3 mt-0.5 max-h-[180px] overflow-y-auto px-3 py-1",
}: {
  children: React.ReactNode;
  autoScroll?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  useEffect(() => {
    if (!autoScroll || !stickRef.current) return;
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  });

  useEffect(() => {
    if (autoScroll) stickRef.current = true;
  }, [autoScroll]);

  const handleScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
  }, []);

  return (
    <div ref={ref} onScroll={handleScroll} className={className}>
      {children}
    </div>
  );
}

function TraceIcon({ kind, phase }: { kind: string; phase: string }) {
  const Icon =
    kind === "rag_retrieval"
      ? Database
      : kind === "llm_final_response"
        ? MessageSquare
        : kind === "llm_observation"
          ? BrainCircuit
          : kind === "llm_generation"
            ? PenLine
            : phase === "writing"
              ? PenLine
              : phase === "planning"
                ? Sparkles
                : phase === "acting"
                  ? Terminal
                  : BrainCircuit;
  return <Icon size={12} strokeWidth={1.6} className="shrink-0" />;
}

function TraceSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  if (!children) return null;
  return (
    <div className="space-y-0.5">
      <div className="not-italic text-[10px] font-semibold tracking-[0.04em] text-[var(--muted-foreground)]/70">
        {title}
      </div>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Per-trace rendering                                                */
/* ------------------------------------------------------------------ */

function TraceRowBody({
  callId,
  callEvents,
  group,
  role,
  kind,
  t,
}: {
  callId: string;
  callEvents: StreamEvent[];
  group: string;
  role: string;
  kind: string;
  t: (key: string) => string;
}) {
  const progressEvents = callEvents.filter((event) => {
    if (event.type !== "progress") return false;
    const traceKind = String(getTraceMeta(event).trace_kind || "");
    if (traceKind === "call_status") return false;
    return event.content.trim().length > 0;
  });
  const toolEvents = callEvents.filter(
    (event) => event.type === "tool_call" || event.type === "tool_result",
  );
  const summaryProgressEvents = progressEvents.filter(
    (event) => String(getTraceMeta(event).trace_layer || "summary") !== "raw",
  );
  const rawProgressEvents = progressEvents.filter(
    (event) => String(getTraceMeta(event).trace_layer || "") === "raw",
  );
  const errorEvents = callEvents.filter(
    (event) => event.type === "error" && event.content.trim().length > 0,
  );
  const thoughtText = getTraceText(callEvents, ["thinking"]);
  const observationText = getTraceText(callEvents, ["observation"]);
  const contentText = getTraceText(callEvents, ["content"]);
  const genericBodyText =
    role === "observe"
      ? observationText
      : role === "retrieve"
        ? ""
        : thoughtText || contentText;
  const inlineSources = callEvents.flatMap((event) => getTraceMeta(event).sources ?? []);

  return (
    <div className="text-[11px] italic leading-[1.6] text-[var(--muted-foreground)]">
      {group === "react_round" ? (
        <div className="space-y-2">
          <TraceSection title={t("Thought")}>
            {thoughtText ? <MarkdownRenderer content={thoughtText} variant="trace" /> : null}
          </TraceSection>
          <TraceSection title={t("Tool")}>
            {toolEvents.length > 0 ? (
              <div className="space-y-0.5">
                {toolEvents.map((event, idx) => {
                  if (event.type === "tool_call") {
                    const formattedArgs = formatTraceArgs(event.metadata?.args);
                    return (
                      <div key={`${callId}-tool-call-${idx}`}>
                        <span className="opacity-50">→ </span>
                        <span>{event.content}</span>
                        {formattedArgs && (
                          <pre className="ml-3 mt-0.5 whitespace-pre-wrap break-words rounded-md bg-[var(--muted)] px-2 py-1 font-mono text-[10px] not-italic leading-[1.5] text-[var(--muted-foreground)]">
                            {formattedArgs}
                          </pre>
                        )}
                      </div>
                    );
                  }
                  return (
                    <div key={`${callId}-tool-result-${idx}`}>
                      <span className="opacity-50">✓ </span>
                      <span>{String(event.metadata?.tool ?? "result")}</span>
                      {event.content && (
                        <div className="ml-3 mt-0.5">
                          <MarkdownRenderer content={event.content} variant="trace" />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : null}
          </TraceSection>
          <TraceSection title={t("Observe")}>
            {observationText ? <MarkdownRenderer content={observationText} variant="trace" /> : null}
          </TraceSection>
        </div>
      ) : (
        <div className="space-y-1">
          {summaryProgressEvents.length > 0 && (
            <div className="space-y-0.5">
              {summaryProgressEvents.map((event, idx) => (
                <div key={`${callId}-progress-${idx}`} className="opacity-70">
                  {event.content}
                </div>
              ))}
            </div>
          )}

          {(role === "retrieve" || kind === "math_render_output") && rawProgressEvents.length > 0 && (
            <div className="space-y-0.5">
              <div className="not-italic text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--muted-foreground)]">
                {t("Raw logs")}
              </div>
              <div className="max-h-[200px] overflow-y-auto rounded-md border border-[var(--border)] bg-[#292524] px-3 py-2 font-mono text-[10px] leading-[1.55] text-[#D6D3D1] shadow-inner">
                {rawProgressEvents.map((event, idx) => (
                  <div key={`${callId}-raw-${idx}`} className="whitespace-pre-wrap break-words">
                    {event.content}
                  </div>
                ))}
              </div>
            </div>
          )}

          {toolEvents.length > 0 && (
            <div className="space-y-0.5">
              {toolEvents.map((event, idx) => {
                if (event.type === "tool_call") {
                  const formattedArgs = formatTraceArgs(event.metadata?.args);
                  return (
                    <div key={`${callId}-tool-call-${idx}`}>
                      <span className="opacity-50">→ </span>
                      <span>{event.content}</span>
                      {formattedArgs && (
                        <pre className="ml-3 mt-0.5 whitespace-pre-wrap break-words rounded-md bg-[var(--muted)] px-2 py-1 font-mono text-[10px] not-italic leading-[1.5] text-[var(--muted-foreground)]">
                          {formattedArgs}
                        </pre>
                      )}
                    </div>
                  );
                }
                return (
                  <div key={`${callId}-tool-result-${idx}`}>
                    <span className="opacity-50">✓ </span>
                    <span>{String(event.metadata?.tool ?? "result")}</span>
                    {event.content && (
                      <div className="ml-3 mt-0.5">
                        <MarkdownRenderer content={event.content} variant="trace" />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {genericBodyText && (
            <div className="mt-1">
              <MarkdownRenderer content={genericBodyText} variant="trace" />
            </div>
          )}
        </div>
      )}

      {inlineSources.length > 0 && (
        <div className="mt-1 opacity-50">
          {t("Sources")}:{" "}
          {inlineSources.map((source, idx) => (
            <span key={`${callId}-source-${idx}`}>
              {idx > 0 && " · "}
              {String(source.title || source.query || source.type || "source")}
            </span>
          ))}
        </div>
      )}

      {errorEvents.length > 0 && (
        <div className="mt-1 space-y-0.5">
          {errorEvents.map((event, idx) => (
            <div key={`${callId}-error-${idx}`} className="text-red-400/80">
              ✗ {event.content}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function hasExpandableContent(callEvents: StreamEvent[], group: string, role: string) {
  const progressEvents = callEvents.filter((event) => {
    if (event.type !== "progress") return false;
    const traceKind = String(getTraceMeta(event).trace_kind || "");
    if (traceKind === "call_status") return false;
    return event.content.trim().length > 0;
  });
  const toolEvents = callEvents.filter(
    (event) => event.type === "tool_call" || event.type === "tool_result",
  );
  const summaryProgressEvents = progressEvents.filter(
    (event) => String(getTraceMeta(event).trace_layer || "summary") !== "raw",
  );
  const rawProgressEvents = progressEvents.filter(
    (event) => String(getTraceMeta(event).trace_layer || "") === "raw",
  );
  const errorEvents = callEvents.filter(
    (event) => event.type === "error" && event.content.trim().length > 0,
  );
  const thoughtText = getTraceText(callEvents, ["thinking"]);
  const observationText = getTraceText(callEvents, ["observation"]);
  const contentText = getTraceText(callEvents, ["content"]);
  const genericBodyText =
    role === "observe"
      ? observationText
      : role === "retrieve"
        ? ""
        : thoughtText || contentText;
  const inlineSources = callEvents.flatMap((event) => getTraceMeta(event).sources ?? []);

  return (
    toolEvents.length > 0 ||
    summaryProgressEvents.length > 0 ||
    rawProgressEvents.length > 0 ||
    errorEvents.length > 0 ||
    Boolean(genericBodyText) ||
    inlineSources.length > 0 ||
    (group === "react_round" && (Boolean(thoughtText) || Boolean(observationText)))
  );
}

/* ------------------------------------------------------------------ */
/*  CallTracePanel                                                     */
/* ------------------------------------------------------------------ */

export function CallTracePanel({
  events,
  isStreaming,
}: {
  events: StreamEvent[];
  isStreaming?: boolean;
}) {
  const { t } = useTranslation();
  const [nowSeconds, setNowSeconds] = useState(() => Date.now() / 1000);

  useEffect(() => {
    if (!isStreaming) return;
    const timer = window.setInterval(() => setNowSeconds(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [isStreaming]);

  const traceGroups = useMemo(() => {
    const groups: TraceItem[] = [];
    const indexById = new Map<string, number>();

    for (const event of events) {
      const callId = String(getTraceMeta(event).call_id || "");
      if (!callId) continue;
      const existingIndex = indexById.get(callId);
      if (existingIndex === undefined) {
        indexById.set(callId, groups.length);
        groups.push({ callId, events: [event] });
      } else {
        groups[existingIndex].events.push(event);
      }
    }

    return groups;
  }, [events]);

  const displayItems = useMemo(() => buildDisplayItems(traceGroups), [traceGroups]);

  if (!traceGroups.length) return null;

  function renderTraceRow(
    { callId, events: callEvents }: TraceItem,
    isGloballyLast: boolean,
    nested: boolean,
  ) {
    const first = callEvents[0];
    const meta = getTraceMeta(first);
    const phase = String(meta.phase || first.stage || "");
    const role = getTraceRole(callEvents);
    const group = getTraceGroup(callEvents);
    const kind = getTraceCallKind(callEvents);
    const header = getTraceHeader(callEvents, nowSeconds, nested);
    const active = Boolean(isStreaming) && isGloballyLast && isTracePending(callEvents);
    const isFinalResponse = kind === "llm_final_response";

    if (isFinalResponse) return null;

    const expandable = hasExpandableContent(callEvents, group, role);
    if (!expandable && !active) return null;

    const summaryRow = (
      <div className="flex list-none items-center gap-2 py-0.5 not-italic text-[12px] font-medium text-[var(--muted-foreground)]">
        {expandable ? (
          <ChevronDown
            size={12}
            className="shrink-0 transition-transform group-open:rotate-180"
          />
        ) : (
          <span className="w-3 shrink-0" />
        )}
        <TraceIcon kind={kind} phase={phase} />
        <span>{header}</span>
        {active && <Loader2 size={11} className="animate-spin" />}
      </div>
    );

    if (!expandable) {
      return <div key={callId}>{summaryRow}</div>;
    }

    return (
      <details key={callId} open={active} className="group">
        <summary className="list-none cursor-pointer hover:text-[var(--foreground)] [&::-webkit-details-marker]:hidden">
          {summaryRow}
        </summary>
        {nested ? (
          <div className="ml-5 mr-3 mt-0.5 px-3 py-1">
            <TraceRowBody callId={callId} callEvents={callEvents} group={group} role={role} kind={kind} t={t} />
          </div>
        ) : (
          <ScrollableTraceBody autoScroll={active}>
            <TraceRowBody callId={callId} callEvents={callEvents} group={group} role={role} kind={kind} t={t} />
          </ScrollableTraceBody>
        )}
      </details>
    );
  }

  return (
    <div className="mb-3 space-y-0.5">
      {displayItems.map((item, displayIdx) => {
        const isLastDisplayItem = displayIdx === displayItems.length - 1;

        if (item.kind === "step") {
          const roundCount = item.traces.filter((tr) => getTraceGroup(tr.events) === "react_round").length;
          const lastTrace = item.traces[item.traces.length - 1];
          const isActiveStep =
            Boolean(isStreaming) && isLastDisplayItem && isTracePending(lastTrace.events);
          const stepDuration = isActiveStep ? "" : getStepGroupDuration(item.traces);

          return (
            <details key={item.stepId} open={isActiveStep || undefined} className="group/step">
              <summary className="list-none cursor-pointer hover:text-[var(--foreground)] [&::-webkit-details-marker]:hidden">
                <div className="flex items-center gap-2 py-0.5 not-italic text-[12px] font-medium text-[var(--muted-foreground)]">
                  <ChevronDown
                    size={12}
                    className="shrink-0 transition-transform group-open/step:rotate-180"
                  />
                  <Sparkles size={12} strokeWidth={1.6} className="shrink-0" />
                  <span>Step {item.stepId}</span>
                  <span className="text-[11px] opacity-60">
                    {roundCount} {roundCount === 1 ? "round" : "rounds"}
                    {stepDuration ? ` · ${stepDuration}` : ""}
                  </span>
                  {isActiveStep && <Loader2 size={11} className="animate-spin" />}
                </div>
              </summary>
              <ScrollableTraceBody
                autoScroll={isActiveStep}
                className="ml-5 mr-3 mt-0.5 max-h-[280px] overflow-y-auto px-3 py-1"
              >
                <div className="text-[11px] italic leading-[1.6] text-[var(--muted-foreground)]">
                  {item.traces.map((trace, idx) => {
                    const trGroup = getTraceGroup(trace.events);
                    const trKind = getTraceCallKind(trace.events);
                    const trRole = getTraceRole(trace.events);
                    const trMeta = getTraceMeta(trace.events[0]);

                    if (trKind === "llm_final_response") return null;

                    if (trGroup === "react_round") {
                      const roundNum = trMeta.round;
                      const duration = getTraceDurationLabel(trace.events);
                      const thoughtText = getTraceText(trace.events, ["thinking"]);
                      const observationText = getTraceText(trace.events, ["observation"]);
                      const traceToolEvents = trace.events.filter(
                        (e) => e.type === "tool_call" || e.type === "tool_result",
                      );
                      const isLastInStep = idx === item.traces.length - 1;
                      const roundActive =
                        Boolean(isStreaming) && isLastDisplayItem && isLastInStep && isTracePending(trace.events);

                      return (
                        <div key={trace.callId}>
                          {idx > 0 && <div className="my-1.5 h-px bg-[var(--border)]/30" />}
                          <div className="mb-1 flex items-center gap-1.5 not-italic text-[11px]">
                            <span className="font-bold uppercase tracking-[0.08em] text-[var(--muted-foreground)]">
                              Round {roundNum}
                            </span>
                            {duration && (
                              <span className="font-normal text-[var(--muted-foreground)]/40">{duration}</span>
                            )}
                            {roundActive && <Loader2 size={10} className="animate-spin" />}
                          </div>
                          <div className="space-y-1.5 pl-0.5">
                            <TraceSection title={t("Thought")}>
                              {thoughtText ? (
                                <MarkdownRenderer content={thoughtText} variant="trace" />
                              ) : null}
                            </TraceSection>
                            <TraceSection title={t("Tool")}>
                              {traceToolEvents.length > 0 ? (
                                <div className="space-y-0.5">
                                  {traceToolEvents.map((ev, ei) => {
                                    if (ev.type === "tool_call") {
                                      const fa = formatTraceArgs(ev.metadata?.args);
                                      return (
                                        <div key={`${trace.callId}-tc-${ei}`}>
                                          <span className="opacity-50">→ </span>
                                          <span>{ev.content}</span>
                                          {fa && (
                                            <pre className="ml-3 mt-0.5 whitespace-pre-wrap break-words rounded-md bg-[var(--muted)] px-2 py-1 font-mono text-[10px] not-italic leading-[1.5] text-[var(--muted-foreground)]">
                                              {fa}
                                            </pre>
                                          )}
                                        </div>
                                      );
                                    }
                                    return (
                                      <div key={`${trace.callId}-tr-${ei}`}>
                                        <span className="opacity-50">✓ </span>
                                        <span>{String(ev.metadata?.tool ?? "result")}</span>
                                        {ev.content && (
                                          <div className="ml-3 mt-0.5">
                                            <MarkdownRenderer content={ev.content} variant="trace" />
                                          </div>
                                        )}
                                      </div>
                                    );
                                  })}
                                </div>
                              ) : null}
                            </TraceSection>
                            <TraceSection title={t("Observe")}>
                              {observationText ? (
                                <MarkdownRenderer content={observationText} variant="trace" />
                              ) : null}
                            </TraceSection>
                          </div>
                        </div>
                      );
                    }

                    /* Non-round trace (retrieve, tool, etc.) — inline within the step */
                    const inlineHeader = getTraceHeader(trace.events, nowSeconds, true);
                    const progressEvts = trace.events.filter(
                      (e) =>
                        e.type === "progress" &&
                        String(getTraceMeta(e).trace_kind || "") !== "call_status" &&
                        e.content.trim().length > 0,
                    );
                    const rawEvts = progressEvts.filter(
                      (e) => String(getTraceMeta(e).trace_layer || "") === "raw",
                    );
                    const summaryEvts = progressEvts.filter(
                      (e) => String(getTraceMeta(e).trace_layer || "summary") !== "raw",
                    );
                    const inlineToolEvts = trace.events.filter(
                      (e) => e.type === "tool_call" || e.type === "tool_result",
                    );
                    const genericText =
                      trRole === "observe"
                        ? getTraceText(trace.events, ["observation"])
                        : trRole === "retrieve"
                          ? ""
                          : getTraceText(trace.events, ["thinking"]) || getTraceText(trace.events, ["content"]);

                    const hasContent =
                      summaryEvts.length > 0 ||
                      rawEvts.length > 0 ||
                      inlineToolEvts.length > 0 ||
                      Boolean(genericText);
                    if (!hasContent) return null;

                    return (
                      <div key={trace.callId} className="mt-1.5 pl-0.5">
                        <div className="not-italic text-[11px] font-bold uppercase tracking-[0.08em] text-[var(--muted-foreground)]">
                          {inlineHeader}
                        </div>
                        <div className="mt-0.5 space-y-0.5">
                          {summaryEvts.map((ev, ei) => (
                            <div key={`${trace.callId}-sp-${ei}`} className="opacity-70">
                              {ev.content}
                            </div>
                          ))}
                          {(trRole === "retrieve" || trKind === "math_render_output") && rawEvts.length > 0 && (
                            <div className="max-h-[160px] overflow-y-auto rounded-md border border-[var(--border)] bg-[#292524] px-3 py-2 font-mono text-[10px] not-italic leading-[1.55] text-[#D6D3D1] shadow-inner">
                              {rawEvts.map((ev, ei) => (
                                <div key={`${trace.callId}-rw-${ei}`} className="whitespace-pre-wrap break-words">
                                  {ev.content}
                                </div>
                              ))}
                            </div>
                          )}
                          {inlineToolEvts.map((ev, ei) => (
                            <div key={`${trace.callId}-it-${ei}`}>
                              <span className="opacity-50">{ev.type === "tool_call" ? "→ " : "✓ "}</span>
                              <span>{ev.type === "tool_call" ? ev.content : String(ev.metadata?.tool ?? "result")}</span>
                            </div>
                          ))}
                          {genericText && (
                            <div className="mt-0.5">
                              <MarkdownRenderer content={genericText} variant="trace" />
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </ScrollableTraceBody>
            </details>
          );
        }

        return renderTraceRow(item.trace, isLastDisplayItem, false);
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  ResearchStagePanel                                                 */
/* ------------------------------------------------------------------ */

function getResearchStageId(event: StreamEvent): ResearchStageCard["id"] {
  const meta = getTraceMeta(event);
  const explicitStage = String((event.metadata as Record<string, unknown> | undefined)?.research_stage_card || "");
  if (
    explicitStage === "understand" ||
    explicitStage === "decompose" ||
    explicitStage === "evidence" ||
    explicitStage === "result"
  ) {
    return explicitStage;
  }
  const stage = String(event.stage || meta.phase || "");
  const text = String(event.content || "").toLowerCase();
  const agent = String((event.metadata as Record<string, unknown> | undefined)?.agent_name || "");

  if (stage === "reporting") return "result";
  if (stage === "decomposing" || agent === "decompose_agent") return "decompose";
  if (stage === "rephrasing" || agent === "rephrase_agent") return "understand";
  if (stage === "planning") {
    if (text.includes("decompose") || text.includes("queue")) return "decompose";
    return "understand";
  }
  return "evidence";
}

function formatResearchStageSummary(events: StreamEvent[], fallback: string) {
  const progressEvents = events.filter(
    (event) => event.type === "progress" && event.content.trim().length > 0,
  );
  const lastProgress = progressEvents.at(-1)?.content.trim();
  if (lastProgress) {
    return humanizeQuestionId(titleCase(lastProgress.replaceAll("-", "_")));
  }

  const thought = getTraceText(events, ["thinking"]);
  if (thought) return thought.slice(0, 120);

  const content = getTraceText(events, ["content"]);
  if (content) return content.slice(0, 120);

  return fallback;
}

export function ResearchStagePanel({
  events,
  isStreaming,
}: {
  events: StreamEvent[];
  isStreaming?: boolean;
}) {
  const cards = useMemo<ResearchStageCard[]>(() => {
    return RESEARCH_STAGE_SPECS.map((spec) => ({
      ...spec,
      events: events.filter((event) => getResearchStageId(event) === spec.id),
    })).filter((card) => card.events.length > 0);
  }, [events]);

  if (!cards.length) return null;

  return (
    <div className="mb-3 space-y-0.5">
      {cards.map((card, index) => {
        const hasTrace = card.events.some((event) => Boolean(getTraceMeta(event).call_id));
        const active =
          Boolean(isStreaming) &&
          index === cards.length - 1 &&
          card.events.some((event) => isTracePending([event]) || event.type === "progress");
        const summary = formatResearchStageSummary(card.events, card.hint);

        return (
          <div key={card.id}>
            <div className="flex items-center gap-2 py-1 text-[12px] text-[var(--muted-foreground)]">
              <span className="font-semibold">{card.title}</span>
              <span className="text-[11px] opacity-60">{summary}</span>
              {active && <Loader2 size={11} className="animate-spin text-[var(--primary)]" />}
            </div>
            {hasTrace ? <CallTracePanel events={card.events} isStreaming={isStreaming} /> : null}
          </div>
        );
      })}
    </div>
  );
}
