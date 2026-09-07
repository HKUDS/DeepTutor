"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { formatTurnDuration, getTurnDurationSeconds } from "@/lib/trace-timing";
import { describeProviderTool, type ToolProvider } from "@/lib/trace-tools";
import type { StreamEvent } from "@/features/chat/model/protocol";
import {
  ActivityDetailGrid,
  ActivityDivider,
  ActivityHeader,
  ActivityRow,
  ActivityStack,
  argumentRows,
  type ActivityState,
  type DetailRow,
} from "@/components/activity";
import { MODE_SPEED, MODE_TO_ORB } from "./ActivityOrb";
import type {
  ResearchStageCard,
  ResearchStageId,
  TraceDisplayItem,
  TraceItem,
  TraceMetadata,
} from "./model";
import {
  getCallProvider,
  getLatestToolProgress,
  getToolProvider,
  getTraceCallKind,
  getTraceGroup,
  getTraceMeta,
  getTraceRole,
  groupTraceEvents,
  hasRenderableCallTrace as selectHasRenderableCallTrace,
  isChatLoopAnswerContent,
  isNarrationRound,
  isTracePending,
  selectTraceDisplayItems,
} from "./selectors";

// `title` and `hint` are i18n keys resolved via `t(...)` at render time so the
// stage banner follows the active UI language instead of being locked to one.
const RESEARCH_STAGE_SPECS: Array<{
  id: ResearchStageId;
  titleKey: string;
  hintKey: string;
}> = [
  {
    id: "understand",
    titleKey: "research.stage.understand.title",
    hintKey: "research.stage.understand.hint",
  },
  {
    id: "decompose",
    titleKey: "research.stage.decompose.title",
    hintKey: "research.stage.decompose.hint",
  },
  {
    id: "evidence",
    titleKey: "research.stage.evidence.title",
    hintKey: "research.stage.evidence.hint",
  },
  {
    id: "result",
    titleKey: "research.stage.result.title",
    hintKey: "research.stage.result.hint",
  },
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function titleCase(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Collapse whitespace and clip to ``max`` chars with an ellipsis. */
/**
 * Flatten markdown-ish prose into one line of plain text for a folded row.
 *
 * Not a markdown parser — it strips the few marks that would otherwise show
 * up as literal punctuation in a preview (emphasis, headings, list bullets,
 * code fences) and collapses whitespace. Anything it misses degrades to
 * showing the raw character, which is acceptable in a one-line teaser.
 */
function plainPreview(value: string, max = 140) {
  const flat = value
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s{0,3}[-*+]\s+/gm, "")
    .replace(/\*\*([^*]*)\*\*/g, "$1")
    .replace(/[*_]{1,2}([^*_]*)[*_]{1,2}/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

function clip(value: string, max = 56) {
  const text = value.replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** Last path segment (handles both / and \\ separators). */
function basename(path: string) {
  const trimmed = path.replace(/[/\\]+$/, "");
  const parts = trimmed.split(/[/\\]/);
  return parts[parts.length - 1] || trimmed;
}

/** A trace-row glyph: either a hand-drawn Mark or a lucide icon. Both accept
 *  this prop subset, so the row renders them uniformly. */
type ToolDescriptor = {
  /** Human action verb (already translated). */
  verb: string;
  /** The concrete artifact this call touched (file, query, …), or null. */
  chip: string | null;
  /** Render the chip in a mono face (code / paths / commands). */
  mono: boolean;
};

/**
 * Maps a tool call to the activity-row vocabulary: a hand-drawn glyph (the
 * same organic mark family as the status header — see {@link CommandMark}
 * &c.), a human action verb ("Running command", "Reading skill"), and a
 * compact chip naming the artifact it acted on (the command, the file, the
 * query). Falls back to a humanized tool name + generic mark for unknown
 * tools so new tools still read sensibly without a code change.
 *
 * `provider` short-circuits the switch for tools that come from an MCP server
 * or an installed CLI app. Their names are *generated*, so the fallback would
 * title-case a machine string — "Mcp Wolfram Wolframalpha" — and tell the reader
 * neither which service is being used nor what it was asked to do.
 */
function describeToolCall(
  toolName: string,
  args: Record<string, unknown> | undefined,
  t: (key: string, opts?: Record<string, unknown>) => string,
  provider?: ToolProvider | null,
): ToolDescriptor {
  const a = args ?? {};
  const str = (value: unknown) =>
    typeof value === "string" ? value.trim() : "";

  // An external provider's row is decided in `lib/trace-tools` — the whole
  // decision is data there, so it is unit-tested; only the glyph is resolved
  // here, where the marks live.
  const providerRow = describeProviderTool(toolName, args, provider, t);
  if (providerRow) {
    return {
      verb: providerRow.verb,
      chip: providerRow.chip,
      mono: providerRow.mono,
    };
  }
  const host = (url: string) => {
    if (!url) return "";
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch {
      return url;
    }
  };

  switch (toolName) {
    case "exec":
      return {
        verb: a.language === "shell" ? t("Running command") : t("Running code"),
        chip:
          a.language === "shell"
            ? clip(str(a.code), 48) || null
            : str(a.language) || t("Python"),
        mono: true,
      };
    case "rag":
      return {
        verb: t("Searching knowledge"),
        chip: clip(str(a.query)) || null,
        mono: false,
      };
    case "kb_files":
      return {
        verb: t("Listing knowledge base files"),
        chip: str(a.kb_name) || null,
        mono: false,
      };
    case "web_search":
      return {
        verb: t("Searching the web"),
        chip: clip(str(a.query)) || null,
        mono: false,
      };
    case "paper_search":
      return {
        verb: t("Searching papers"),
        chip: clip(str(a.query)) || null,
        mono: false,
      };
    case "web_fetch":
      return {
        verb: t("Fetching page"),
        chip: host(str(a.url)) || null,
        mono: true,
      };
    case "read_skill":
      return {
        verb: t("Reading skill"),
        chip: str(a.name) || null,
        mono: false,
      };
    case "load_tools": {
      const names = Array.isArray(a.names)
        ? (a.names as unknown[]).map((n) => String(n))
        : [];
      return {
        verb: t("Loading tools"),
        chip: names.join(", ") || null,
        mono: true,
      };
    }
    case "read_source":
      return {
        verb: t("Reading source"),
        chip: str(a.source_id) || null,
        mono: false,
      };
    case "read_file":
      return {
        verb: t("Reading file"),
        chip: basename(str(a.path)) || null,
        mono: true,
      };
    case "write_file":
      return {
        verb: t("Writing file"),
        chip: basename(str(a.path)) || null,
        mono: true,
      };
    case "edit_file":
      return {
        verb: t("Editing file"),
        chip: basename(str(a.path)) || null,
        mono: true,
      };
    case "list_dir":
      return {
        verb: t("Listing files"),
        chip: basename(str(a.path)) || null,
        mono: true,
      };
    case "write_note":
      return {
        verb: t("Writing note"),
        chip: clip(str(a.title), 40) || null,
        mono: false,
      };
    case "read_memory":
      return {
        verb: t("Recalling memory"),
        chip: null,
        mono: false,
      };
    case "write_memory":
      return {
        verb: t("Saving memory"),
        chip: null,
        mono: false,
      };
    case "reason":
      return {
        verb: t("Reasoning"),
        chip: clip(str(a.query)) || null,
        mono: false,
      };
    case "brainstorm":
      return {
        verb: t("Brainstorming"),
        chip: clip(str(a.topic)) || null,
        mono: false,
      };
    case "ask_user":
      return {
        verb: t("Asking you"),
        chip: null,
        mono: false,
      };
    case "invoke_other":
      return {
        verb: t("Proposing a Partner follow-up"),
        chip: str(a.target_partner_id)
          ? `@${str(a.target_partner_id).replace(/^@/, "")}`
          : null,
        mono: false,
      };
    case "github":
      return {
        verb: t("Querying GitHub"),
        chip: str(a.target) || null,
        mono: true,
      };
    case "geogebra_analysis":
      return {
        verb: t("Analyzing figure"),
        chip: null,
        mono: false,
      };
    case "visualize":
      return {
        verb: t("Visualizing"),
        chip: null,
        mono: false,
      };
    case "math_animator":
      return { verb: t("Animating"), chip: null, mono: false };
    default:
      return {
        verb: titleCase(toolName),
        chip: null,
        mono: false,
      };
  }
}

function humanizeQuestionId(
  value: string,
  t?: (key: string, opts?: Record<string, unknown>) => string,
) {
  return value.replace(/\bq_(\d+)\b/gi, (_match, n) =>
    t ? t("Question {{n}}", { n }) : `Question ${n}`,
  );
}

function getTraceLabel(
  events: StreamEvent[],
  t?: (key: string, opts?: Record<string, unknown>) => string,
) {
  for (const event of events) {
    const meta = getTraceMeta(event);
    if (meta.label) return humanizeQuestionId(String(meta.label), t);
  }
  const fallback = events[0]?.stage || "trace";
  return humanizeQuestionId(titleCase(fallback), t);
}

/**
 * The external provider this trace's tool belongs to, or null for a built-in.
 *
 * Exported for tests: this and {@link getLatestToolProgress} are the wiring
 * between what the backend stamps on a turn's events and what the row shows, and
 * they are checked against events recorded from a real LLM turn
 * (`tests/fixtures/provider-trace-events.json`).
 *
 * Scanned across the group rather than read off the `tool_call` event alone: the
 * status and progress events carry it too, and a group whose opening event was
 * dropped (a reconnect mid-turn) should still be labelled correctly.
 */
export { getLatestToolProgress, getToolProvider } from "./selectors";

function getTraceHeader(
  events: StreamEvent[],
  nested?: boolean,
  t: (key: string, opts?: Record<string, unknown>) => string = (k) => k,
) {
  const label = getTraceLabel(events, t);
  const role = getTraceRole(events);
  const group = getTraceGroup(events);
  const kind = getTraceCallKind(events);
  const meta = getTraceMeta(events[0]);

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
  } else if (kind === "context_exploration") {
    // The pre-pass that investigates the turn's attached sources before
    // answering. Noun header for the trace row — the turn-level status row
    // carries the verb form ("Exploring your context…") so the two never
    // read as the same label stacked on itself.
    title = t("Context exploration");
  } else if (role === "retrieve") {
    title = t("Retrieve");
  } else if (role === "explore" || kind === "agent_loop_round") {
    title = t("Exploring");
  } else if (kind === "tool_planning") {
    title = t("Tool call");
  } else if (group === "react_round") {
    if (nested) {
      title = meta.round ? t("Round {{n}}", { n: meta.round }) : label;
    } else {
      const step = meta.step_id ? t("Step {{n}}", { n: meta.step_id }) : "";
      const round = meta.round ? t("Round {{n}}", { n: meta.round }) : label;
      title = [step, round].filter(Boolean).join(" · ");
    }
  } else if (role === "plan" && kind === "llm_planning") {
    title = t("Plan");
  } else if (role === "observe" || kind === "llm_observation") {
    title = t("Observe");
  } else if (role === "quiz_question" || kind === "quiz_question_emitted") {
    // Each quiz question gets its own sub-trace card; index is 0-based in
    // metadata, so display as 1-based for the user.
    const idx = Number(meta.question_index);
    title = Number.isFinite(idx)
      ? t("Question {{n}}", { n: idx + 1 })
      : t("Question");
  } else if (role === "response" || kind === "llm_final_response") {
    title = t("Response");
  } else if (role === "reflection" || kind === "tool_result_reflection") {
    // Tool Summarizer sub-trace (Phase 1 of the question pipeline). The
    // top-level status row carries the verbose "DeepTutor Reflecting…"
    // wording; the sub-trace just labels itself "Reflecting" so the card
    // header stays short.
    title = t("Reflecting");
  } else if (role === "thought" || kind === "llm_reasoning") {
    title = t("Thought");
  } else if (kind === "llm_generation") {
    if (/^generate\s+/i.test(label)) {
      title = t("Generating {{label}}", {
        label: label.replace(/^generate\s+/i, ""),
      });
    } else if (/^write\s+/i.test(label)) {
      title = t("Writing {{label}}", {
        label: label.replace(/^write\s+/i, ""),
      });
    }
  }

  return title;
}

// Chat-loop `content` (call_kind "agent_loop_round") is the model's
// user-facing text. Whether it belongs in the trace depends on the round:
//   - a NARRATION round (the round ended with a tool call) → its text was
//     the model's commentary before acting. It is stripped from the answer
//     bubble, so it MUST surface in the trace.
//   - a FINISH round (the round ended with no tool call) → its text IS the
//     answer bubble; keep it out of the trace to avoid duplication.
// The differentiator is the round's own ``call_status`` marker (call_role).
function getTraceText(
  events: StreamEvent[],
  eventTypes: Array<StreamEvent["type"]>,
  // When the caller knows this group is a narration round, its
  // ``agent_loop_round`` content is trace material and should NOT be
  // filtered out as answer-bubble text.
  includeChatLoopContent = false,
) {
  const textEvents = events.filter(
    (event) =>
      eventTypes.includes(event.type) &&
      event.content.trim().length > 0 &&
      (includeChatLoopContent || !isChatLoopAnswerContent(event)),
  );
  if (!textEvents.length) return "";

  const explicitOutputs = textEvents.filter(
    (event) => String(getTraceMeta(event).trace_kind || "") === "llm_output",
  );
  if (explicitOutputs.length > 0) {
    return explicitOutputs[explicitOutputs.length - 1].content;
  }

  return textEvents.map((event) => event.content).join("");
}

// Long string values in tool args are almost always base64 payloads
// (image bytes, file blobs) the LLM never typed itself — they were
// server-injected by the chat pipeline. Pretty-printing the raw value
// fills the trace with megabytes of noise, so we elide anything past
// this many characters down to a short summary.
const TRACE_ARGS_MAX_STRING_CHARS = 200;

function elideLongStrings(value: unknown): unknown {
  if (typeof value === "string") {
    if (value.length > TRACE_ARGS_MAX_STRING_CHARS) {
      const head = value.slice(0, 40);
      return `${head}… <${value.length.toLocaleString()} chars elided>`;
    }
    return value;
  }
  if (Array.isArray(value)) {
    return value.map(elideLongStrings);
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = elideLongStrings(v);
    }
    return out;
  }
  return value;
}

function formatTraceArgs(args: unknown) {
  if (args == null) return "";
  try {
    return JSON.stringify(elideLongStrings(args), null, 2);
  } catch {
    return String(args);
  }
}

/**
 * Per-tool nice rendering for ``tool_call`` args. Some tools (notably
 * ``ask_user``) have args that are large structured payloads which the
 * UI also renders as a dedicated card below the trace — dumping the raw
 * JSON twice is just noise. Returning ``null`` falls back to the
 * generic JSON ``<pre>`` block.
 */
function renderNiceToolArgs(
  toolName: string | undefined,
  rawArgs: unknown,
): ReactNode | null {
  if (toolName !== "ask_user" || !rawArgs || typeof rawArgs !== "object") {
    return null;
  }
  const obj = rawArgs as Record<string, unknown>;
  const questions = Array.isArray(obj.questions)
    ? (obj.questions as Array<Record<string, unknown>>)
    : [];
  if (questions.length === 0) return null;
  return (
    <ul className="ml-3 mt-0.5 space-y-0.5 text-[10.5px] leading-[1.5] not-italic">
      {questions.map((q, idx) => {
        const prompt = String(q.prompt ?? q.question ?? "").trim();
        if (!prompt) return null;
        return (
          <li
            key={idx}
            className="flex items-start gap-1.5 text-[var(--muted-foreground)]"
          >
            <span className="shrink-0 tabular-nums opacity-50">{idx + 1}.</span>
            <span className="min-w-0 flex-1">{prompt}</span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Display name for a retrieval / search engine slug.
 *
 * The backend keeps the authoritative label table (`provider_runtime.py`),
 * but it is only reachable through the settings endpoints and a trace row has
 * no business calling those. `titleCase` handles most slugs; this table is
 * only the ones whose capitalisation it cannot guess.
 */
const PROVIDER_LABELS: Record<string, string> = {
  lightrag: "LightRAG",
  raganything: "RAGAnything",
  pageindex: "PageIndex",
  llamaindex: "LlamaIndex",
  graphrag: "GraphRAG",
  duckduckgo: "DuckDuckGo",
  ddg: "DuckDuckGo",
  openai: "OpenAI",
  aliyun_iqs: "Aliyun IQS",
  iqs: "IQS",
  bocha: "Bocha",
  zhipu: "Zhipu",
};

function providerLabel(slug: string): string {
  return PROVIDER_LABELS[slug.toLowerCase()] ?? titleCase(slug);
}

/**
 * Tools whose row names its engine.
 *
 * Only the ones the user picks a provider for. Which engine answered is the
 * whole difference between two calls that otherwise render identically, and
 * it is the part of the pipeline the reader configured themselves — so
 * "Perplexity 联网搜索" says more than "联网搜索" at no extra width.
 */
const ENGINE_NAMED_TOOLS = new Set([
  "web_search",
  "rag_search",
  "rag",
  "paper_search",
]);

/** A tool call together with its result, once one arrives. */
type ToolExchange = { call: StreamEvent; result: StreamEvent | null };

/**
 * Pair each `tool_call` with the `tool_result` that follows it.
 *
 * Needed because the two arrive as separate events, and rendering them as
 * separate blocks is what made the old detail body read as a list of
 * fragments rather than as one exchange.
 */
function pairToolEvents(events: StreamEvent[]): ToolExchange[] {
  const out: ToolExchange[] = [];
  for (const event of events) {
    if (event.type === "tool_call") {
      out.push({ call: event, result: null });
      continue;
    }
    const open = out[out.length - 1];
    if (open && !open.result) open.result = event;
    // A result with no call ahead of it — a resumed turn, or a call event
    // filtered upstream — still has to render, so it stands alone.
    else out.push({ call: event, result: null });
  }
  return out;
}

/**
 * The second level of a tool row: what went in, and what came back.
 *
 * Laid out as one label/value grid, because that is what the content is —
 * `query`, then `result`, on a shared left edge. The previous version put the
 * arguments in a pretty-printed JSON block and the result in a separately
 * ruled box below it, which spent most of its area on braces, quotes and a
 * second vertical rule. The row's own first level already names the action in
 * human terms, so this level never restates it either.
 */
function ToolExchangeDetail({
  exchange,
  showToolName,
}: {
  exchange: ToolExchange;
  showToolName: boolean;
}) {
  const { call, result } = exchange;
  const toolName = (call.metadata?.tool as string | undefined) ?? undefined;
  const isCall = call.type === "tool_call";

  const niceArgs = isCall
    ? renderNiceToolArgs(toolName, call.metadata?.args)
    : null;
  const rawArgs = isCall ? call.metadata?.args : undefined;
  const entries = niceArgs ? [] : argumentRows(rawArgs);
  // Non-object args (a bare string, an array) have no keys to lay out; they
  // land under a generic label rather than inventing a shape for them.
  const fallback =
    !niceArgs && entries.length === 0 && rawArgs && typeof rawArgs !== "object"
      ? formatTraceArgs(rawArgs)
      : "";

  const resultText = result?.content?.trim() || (!isCall ? call.content : "");
  const rows: DetailRow[] = [];

  if (showToolName && (toolName || call.content)) {
    rows.push({ key: "tool", value: toolName || call.content, mono: true });
  }
  rows.push(...entries);
  if (fallback) rows.push({ key: "args", value: fallback, mono: true });
  if (resultText) {
    rows.push({
      key: "result",
      value: <MarkdownRenderer content={resultText} variant="trace" />,
    });
  }

  if (!rows.length && !niceArgs) return null;

  return (
    <div>
      <ActivityDetailGrid rows={rows} />
      {niceArgs ?? null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Display-item grouping (step-level)                                 */
/* ------------------------------------------------------------------ */

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
  // A chat round can emit BOTH reasoning (thinking) and narration commentary
  // (content) in a single call; both are trace material and render as
  // separate stacked blocks. Other pipelines keep the legacy "thought or
  // content" fallback so their rows are unchanged.
  const isChatRound = kind === "agent_loop_round";
  const contentText = getTraceText(
    callEvents,
    ["content"],
    isNarrationRound(callEvents),
  );
  const bodyBlocks =
    role === "observe"
      ? [observationText]
      : role === "retrieve"
        ? []
        : isChatRound
          ? [thoughtText, contentText]
          : [thoughtText || contentText];
  const renderableBodyBlocks = bodyBlocks.filter(
    (text): text is string => Boolean(text) && text.trim().length > 0,
  );
  // A connected subagent's native run streams in as ``subagent_event`` progress
  // lines, but those are shown in the side viewer's per-agent tab — keep the
  // inline trace compact (the question + the agent's final reply).
  const plainSummaryEvents = summaryProgressEvents.filter(
    (event) => getTraceMeta(event).trace_kind !== "subagent_event",
  );
  const inlineSources = callEvents.flatMap(
    (event) => getTraceMeta(event).sources ?? [],
  );

  return (
    <div className="text-[11.5px] leading-[1.6] text-[var(--muted-foreground)]">
      {group === "react_round" ? (
        <div className="space-y-2">
          <TraceSection title={t("Thought")}>
            {thoughtText ? (
              <MarkdownRenderer content={thoughtText} variant="trace" />
            ) : null}
          </TraceSection>
          <TraceSection title={t("Tool")}>
            {toolEvents.length > 0 ? (
              <div className="space-y-0.5">
                {pairToolEvents(toolEvents).map((exchange, idx) => (
                  <ToolExchangeDetail
                    key={`${callId}-tool-${idx}`}
                    exchange={exchange}
                    // Inside a round's "Tool" section the name is the only
                    // thing identifying which tool ran.
                    showToolName
                  />
                ))}
              </div>
            ) : null}
          </TraceSection>
          <TraceSection title={t("Observe")}>
            {observationText ? (
              <MarkdownRenderer content={observationText} variant="trace" />
            ) : null}
          </TraceSection>
        </div>
      ) : (
        <div className="space-y-1">
          {plainSummaryEvents.length > 0 && (
            <div className="space-y-0.5">
              {plainSummaryEvents.map((event, idx) => (
                <div key={`${callId}-progress-${idx}`} className="opacity-70">
                  {event.content}
                </div>
              ))}
            </div>
          )}

          {(role === "retrieve" || kind === "math_render_output") &&
            rawProgressEvents.length > 0 && (
              <div className="space-y-0.5">
                <div className="not-italic text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--muted-foreground)]">
                  {t("Raw logs")}
                </div>
                <div className="max-h-[200px] overflow-y-auto rounded-md border border-[var(--border)] bg-[#292524] px-3 py-2 font-mono text-[10px] leading-[1.55] text-[#D6D3D1] shadow-inner">
                  {rawProgressEvents.map((event, idx) => (
                    <div
                      key={`${callId}-raw-${idx}`}
                      className="whitespace-pre-wrap break-words"
                    >
                      {event.content}
                    </div>
                  ))}
                </div>
              </div>
            )}

          {toolEvents.length > 0 && (
            <div className="space-y-1">
              {pairToolEvents(toolEvents).map((exchange, idx) => (
                <ToolExchangeDetail
                  key={`${callId}-tool-${idx}`}
                  exchange={exchange}
                  // The row's own first level already spells the action out,
                  // so repeating the raw tool name here is noise.
                  showToolName={false}
                />
              ))}
            </div>
          )}

          {renderableBodyBlocks.length > 0 && (
            <div className="mt-1 space-y-1.5">
              {renderableBodyBlocks.map((text, idx) => (
                <MarkdownRenderer
                  key={`${callId}-body-${idx}`}
                  content={text}
                  variant="trace"
                />
              ))}
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

function hasExpandableContent(
  callEvents: StreamEvent[],
  group: string,
  role: string,
) {
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
  const contentText = getTraceText(
    callEvents,
    ["content"],
    isNarrationRound(callEvents),
  );
  const genericBodyText =
    role === "observe"
      ? observationText
      : role === "retrieve"
        ? ""
        : thoughtText || contentText;
  const inlineSources = callEvents.flatMap(
    (event) => getTraceMeta(event).sources ?? [],
  );

  return (
    toolEvents.length > 0 ||
    summaryProgressEvents.length > 0 ||
    rawProgressEvents.length > 0 ||
    errorEvents.length > 0 ||
    Boolean(genericBodyText) ||
    inlineSources.length > 0 ||
    (group === "react_round" &&
      (Boolean(thoughtText) || Boolean(observationText)))
  );
}

/* ------------------------------------------------------------------ */
/*  Inline trace rows                                                  */
/* ------------------------------------------------------------------ */

/**
 * One trace = one Claude-style flat activity line in the message flow:
 * a small icon + the meaningful text of this step (reasoning / narration,
 * or a tool action with a tool-name chip) shown inline. There is no boxed
 * header and no always-visible chevron — a faint chevron only appears on
 * hover for rows that carry extra detail.
 *
 * The live step is auto-expanded so its reasoning streams in full; once it
 * completes it folds to a one-line preview (the activity-feed look). A
 * manual toggle pins the row from then on.
 */
function TraceRowItem({
  trace,
  active,
  nested,
}: {
  trace: TraceItem;
  active: boolean;
  nested: boolean;
}) {
  const { t } = useTranslation();
  const [userOpen, setUserOpen] = useState<boolean | null>(null);

  const { callId, events: callEvents } = trace;
  const first = callEvents[0];
  const meta = getTraceMeta(first);
  const phase = String(meta.phase || first?.stage || "");
  const role = getTraceRole(callEvents);
  const group = getTraceGroup(callEvents);
  const kind = getTraceCallKind(callEvents);
  const header = getTraceHeader(callEvents, nested, t);

  if (kind === "llm_final_response") return null;
  const expandable = hasExpandableContent(callEvents, group, role);
  if (!expandable && !active) return null;

  const isToolRow = kind === "tool_planning" || group === "tool_call";
  const isChatRound = kind === "agent_loop_round";
  const isRetrieve = role === "retrieve";
  const narration = isNarrationRound(callEvents);
  // The model's own text-form deliberation — chat-loop reasoning/narration and
  // pipeline "Thought"/"Plan" rounds. Unlike a tool call (whose result is
  // secondary detail worth folding away), here the text IS the substance, so
  // it always streams in full and is never collapsed behind a chevron.
  const isThinking =
    isChatRound ||
    role === "thought" ||
    kind === "llm_reasoning" ||
    kind === "llm_planning";
  // The first level IS the default view: no row opens its own detail on its
  // own. The single exception is the model's own deliberation, which streams
  // in place while its round is live and folds itself away once the round
  // settles — watching it think is the point, re-reading it afterwards is
  // not. The context-exploration pre-pass opts out even of that: its
  // briefing runs long enough to walk the trace up the viewport while the
  // page is pinned to the bottom.
  const isContextExploration = kind === "context_exploration";
  const autoOpen = isThinking && !isContextExploration ? active : false;
  const open = expandable && (userOpen ?? autoOpen);
  // Every row with detail is clickable now, deliberation included — it has to
  // be, since a settled round folds itself and the text has to be reachable.
  const canToggle = expandable;

  const toolCallEvent = callEvents.find((event) => event.type === "tool_call");
  const toolName = String(
    (toolCallEvent &&
      (getTraceMeta(toolCallEvent).tool_name ||
        toolCallEvent.metadata?.tool)) ||
      toolCallEvent?.content ||
      "",
  ).trim();
  const toolArgs = toolCallEvent?.metadata?.args as
    | Record<string, unknown>
    | undefined;

  const thoughtText = getTraceText(callEvents, ["thinking"]).trim();
  const contentText = getTraceText(callEvents, ["content"], narration).trim();

  // Resolve every row into a uniform { icon, headline, chip } triple so the
  // activity feed reads consistently across pipelines. Tool calls get a human
  // action verb + an artifact chip (the Claude-cowork pattern); retrieval
  // surfaces its query; chat reasoning rounds ARE their text (rendered inline
  // when open, clamped to a preview when folded).
  const provider = getToolProvider(callEvents);
  const descriptor =
    isToolRow && toolName
      ? describeToolCall(toolName, toolArgs, t, provider)
      : null;
  // What the provider last said about its own progress. Only MCP servers and
  // CLI apps publish these, and only while the call is open.
  const liveStatus = active ? getLatestToolProgress(callEvents) : "";

  let headline: string;
  let chip: { text: string; mono: boolean } | null = null;

  const engine = getCallProvider(callEvents);

  if (descriptor) {
    headline =
      engine && ENGINE_NAMED_TOOLS.has(toolName)
        ? `${providerLabel(engine)} ${descriptor.verb}`
        : descriptor.verb;
    chip = descriptor.chip
      ? { text: descriptor.chip, mono: descriptor.mono }
      : null;
    // While it runs, how far along it is displaces what it is: the identity is
    // already in the verb, and "fetching pages (30%)" is the only thing that
    // distinguishes a working call from a hung one. It reverts once settled.
    if (liveStatus) chip = { text: liveStatus, mono: false };
    // Name the consult after the agent it targets (e.g. "Consult Subagent
    // test-cc"); the name rides on the streamed subagent events in the group.
    if (toolName === "consult_subagent") {
      const agentName = String(
        callEvents.map((e) => getTraceMeta(e).subagent_name).find(Boolean) ||
          "",
      );
      headline = agentName
        ? `${t("Consult Subagent")} ${agentName}`
        : t("Consult Subagent");
    }
  } else if (isRetrieve) {
    headline = engine ? `${providerLabel(engine)} ${header}` : header;
    const query = clip(
      String(callEvents.map((e) => getTraceMeta(e).query).find(Boolean) || ""),
    );
    chip = query ? { text: query, mono: false } : null;
  } else if (isChatRound) {
    // The label, not the prose. A chat round used to title itself with its
    // own reasoning, which forced the row to clamp onto two or three lines
    // and made it the only row shaped differently from its neighbours. The
    // reasoning now trails the label as this row's content, same as a query
    // trails a search.
    headline = header;
  } else {
    headline = header;
  }
  // What the dot has to say. Deliberately about state, not category: the
  // row's own text already names the category ("联网搜索 …", "检索", or the
  // model's own sentence), so a glyph repeating it spent the one pre-text
  // position in the row on something the reader can already see. Where the
  // step stands is the part the text never says.
  const rowState: ActivityState = callEvents.some(
    (event) => event.type === "error" && event.content.trim().length > 0,
  )
    ? "error"
    : toolName === "ask_user"
      ? "awaiting"
      : active
        ? "running"
        : "done";

  // The model's own deliberation is the one case where the substance lives at
  // level one: a chat round's text IS the row, so an open one renders its
  // markdown inline rather than a structured detail body.
  const deliberation = isChatRound
    ? [thoughtText, contentText].filter(Boolean)
    : [thoughtText || contentText].filter(Boolean);

  return (
    <ActivityRow
      state={rowState}
      // Every row is one line: an action, then what it acted on. For a tool
      // that is verb + query; for deliberation it is the phase label + the
      // opening of the reasoning. The full text is level two.
      title={headline}
      detail={
        chip?.text ??
        (isThinking && deliberation.length
          ? plainPreview(deliberation[0])
          : undefined)
      }
      detailMono={chip?.mono ?? false}
      breathing={active}
      followOpen={autoOpen}
      autoScrollDetail={active}
      className={isChatRound ? "italic" : ""}
    >
      {isThinking ? (
        deliberation.length ? (
          <div
            className={`space-y-1.5 leading-[1.6] ${isChatRound ? "italic" : ""}`}
          >
            {deliberation.map((text, idx) => (
              <MarkdownRenderer
                key={`${callId}-say-${idx}`}
                content={text}
                variant="trace"
              />
            ))}
          </div>
        ) : null
      ) : (
        <TraceRowBody
          callId={callId}
          callEvents={callEvents}
          group={group}
          role={role}
          kind={kind}
          t={t}
        />
      )}
    </ActivityRow>
  );
}

export function CallTracePanel({
  events,
  isStreaming,
  nested = false,
}: {
  events: StreamEvent[];
  isStreaming?: boolean;
  // Kept for callers that render the rows inside their own framed shell;
  // rows are inline either way, ``nested`` only affects sub-row layout.
  nested?: boolean;
}) {
  const { t } = useTranslation();

  const traceGroups = useMemo(() => groupTraceEvents(events), [events]);

  const displayItems: TraceDisplayItem[] = useMemo(
    () => selectTraceDisplayItems(traceGroups),
    [traceGroups],
  );

  // Hide the outer container entirely when no sub-trace ends up being
  // rendered. ``traceGroups`` can be non-empty even when every group is
  // filtered out by ``selectTraceDisplayItems`` (final-response groups and groups
  // tagged ``absorbed_into_final``) — in that case we used to draw an
  // empty bordered box. Check the materialised displayItems instead.
  if (!displayItems.length) return null;

  // Rows flow inline with the message — no outer card, no shared scroll
  // region. Each row manages its own fold state (live-follow + manual pin)
  // and its expanded body has its own bounded scroll area.
  return (
    <ActivityStack className="mb-3">
      {displayItems.map((item, displayIdx) => {
        const isLastDisplayItem = displayIdx === displayItems.length - 1;

        if (item.kind === "step") {
          const lastTrace = item.traces[item.traces.length - 1];
          const isActiveStep =
            Boolean(isStreaming) &&
            isLastDisplayItem &&
            isTracePending(lastTrace.events);

          // A step is a divider, not a level.
          //
          // It used to be a third fold wrapping its own hand-written
          // Round/Thought/Tool/Observe tree — a second renderer for the same
          // trace data, two levels deeper than the flat rows beside it, and
          // auto-expanded while live. Now it just labels the group and its
          // traces are ordinary first-level rows, so every trace in a turn
          // reads, folds and looks the same regardless of which pipeline
          // produced it.
          return (
            <div key={item.stepId} className={displayIdx > 0 ? "mt-2" : ""}>
              <ActivityDivider
                label={t("Step {{n}}", { n: item.stepId })}
                active={isActiveStep}
              />
              <ActivityStack alignUnderOrb={false}>
                {item.traces.map((trace, idx) => (
                  <TraceRowItem
                    key={trace.callId}
                    trace={trace}
                    active={
                      Boolean(isStreaming) &&
                      isLastDisplayItem &&
                      idx === item.traces.length - 1 &&
                      isTracePending(trace.events)
                    }
                    nested={nested}
                  />
                ))}
              </ActivityStack>
            </div>
          );
        }

        const active =
          Boolean(isStreaming) &&
          isLastDisplayItem &&
          isTracePending(item.trace.events);
        return (
          <TraceRowItem
            key={item.trace.callId}
            trace={item.trace}
            active={active}
            nested={nested}
          />
        );
      })}
    </ActivityStack>
  );
}

/* ------------------------------------------------------------------ */
/*  StreamingStatus — breathing "reasoning" / "tool using" indicator   */
/* ------------------------------------------------------------------ */

/* ---- Trace-row glyphs (same hand-drawn family as the status marks) ---- */

type StreamingMode =
  | "reasoning"
  | "tool_using"
  | "responding"
  | "responded"
  | "planning"
  | "exploring"
  | "quizzing"
  | "reflecting";

/**
 * Picks the status label shown above the trace card.
 *
 * We scan in reverse so each round's latest signal wins — a tool result
 * mid-iteration flips the label back to reasoning, a planning chunk
 * arriving after a tool flips it to planning, etc. Per-mode mapping:
 *
 *   ``agent_loop_round``     → exploring  (chat exploring loop)
 *   ``llm_planning`` chunks  → planning   (solve plan / replan / pre-retrieve)
 *   ``tool_call`` event      → tool_using (any explicit tool call)
 *   ``llm_final_response``
 *     stage=``writing``      → responding (solve synthesize, also chat default)
 *   ``llm_reasoning`` chunks → reasoning  (generic reasoning trace)
 *
 * Falls back to ``reasoning`` while events are still warming up.
 */
function detectStreamingMode(
  events: StreamEvent[],
  hasFinalContent: boolean,
  isStreaming: boolean,
): StreamingMode {
  if (!isStreaming) return "responded";

  for (let idx = events.length - 1; idx >= 0; idx -= 1) {
    const event = events[idx];
    const meta = (event.metadata ?? {}) as Record<string, unknown>;
    const callKind = String(meta.call_kind ?? "");

    if (event.type === "tool_call") {
      // Tool calls inherit the active stage so the top-level status stays
      // coherent (e.g., a rag call during explore reads as "Exploring",
      // not generic "Tool Calling").
      if (event.stage === "exploring") return "exploring";
      if (event.stage === "quizzing") return "quizzing";
      return "tool_using";
    }
    if (event.type === "tool_result") {
      // Tool finished — keep scanning for the iteration's actual mode.
      continue;
    }
    // Quiz pipeline emits one ``quiz_question_emitted`` content event per
    // question with the structured qa_pair in metadata — that's the signal
    // the quizzing phase is active.
    if (callKind === "agent_loop_round") {
      // The chat loop streams user-facing text as `content` (a short
      // narration before a tool call, or the finish answer): show
      // "responding" while text is flowing; thinking keeps "exploring".
      return event.type === "content" ? "responding" : "exploring";
    }
    if (callKind === "quiz_question_emitted") return "quizzing";
    // Question pipeline's Tool Summarizer (Phase 1 reflection over a raw
    // tool result) streams chunks under ``call_kind="tool_result_reflection"``.
    // While those chunks are arriving — and until the next reasoning / tool
    // event flips the mode again — the top-level status row reads
    // "DeepTutor Reflecting…".
    if (callKind === "tool_result_reflection") return "reflecting";
    if (event.type === "content" && callKind === "llm_final_response") {
      // Some pipelines stream response text while an exploration stage is
      // still open; keep the top-level title on "DeepTutor Exploring…" until
      // the bus moves on.
      if (event.stage === "exploring") return "exploring";
      if (event.stage === "writing") return "responding";
      return "responding";
    }
    if (callKind === "llm_planning") return "planning";
    if (event.type === "thinking" && callKind === "llm_reasoning") {
      if (event.stage === "exploring") return "exploring";
      if (event.stage === "quizzing") return "quizzing";
      return "reasoning";
    }
  }
  if (hasFinalContent) return "responding";
  return "reasoning";
}

function parsePositiveInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return Math.floor(value);
  }
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
  }
  return null;
}

function getResearchTopicIndex(meta: TraceMetadata): number | null {
  const explicit = parsePositiveInt(meta.topic_index);
  if (explicit) return explicit;

  const searchable = [meta.block_id, meta.call_id, meta.trace_id]
    .map((value) => String(value || ""))
    .join(" ");
  const match = /\bblock_(\d+)\b/.exec(searchable);
  return match ? parsePositiveInt(match[1]) : null;
}

function getDeepResearchStatusLabel(
  events: StreamEvent[],
  t: (key: string, opts?: Record<string, unknown>) => string,
  isStreaming: boolean,
) {
  if (!isStreaming) return null;

  for (let idx = events.length - 1; idx >= 0; idx -= 1) {
    const event = events[idx];
    if (event.source !== "deep_research") continue;

    const meta = getTraceMeta(event);
    const key = String(meta.research_status_key || "");

    if (key === "decompose_target" || event.stage === "decomposing") {
      return t("Decomposing Target");
    }

    if (key === "research_topic" || event.stage === "researching") {
      const topicIndex = getResearchTopicIndex(meta);
      return topicIndex
        ? t("Researching Topic #{{n}}", { n: topicIndex })
        : t("Researching Topic");
    }

    if (key === "report_intro") return t("Reporting Intro");
    if (key === "report_outline") return t("Reporting Outline");
    if (key === "report_conclusion") return t("Reporting Conclusion");
    if (key === "report_section") {
      const sectionIndex = parsePositiveInt(meta.section_index);
      return sectionIndex
        ? t("Reporting Section #{{n}}", { n: sectionIndex })
        : t("Reporting Section");
    }

    if (event.stage === "reporting") {
      const label = String(meta.label || "").toLowerCase();
      if (label.includes("intro") || label.includes("引言")) {
        return t("Reporting Intro");
      }
      if (label.includes("conclusion") || label.includes("结论")) {
        return t("Reporting Conclusion");
      }
      if (label.includes("section") || label.includes("章节")) {
        const sectionIndex = parsePositiveInt(meta.section_index);
        return sectionIndex
          ? t("Reporting Section #{{n}}", { n: sectionIndex })
          : t("Reporting Section");
      }
      return t("Reporting");
    }
  }

  return null;
}

// While the explore_context pre-pass is the most recent activity, the
// turn-level status reads "Exploring Your Contexts" instead of the generic
// reasoning label. Mirrors getDeepResearchStatusLabel: a backward scan that
// bails as soon as a later (answer-phase) activity is seen.
function getExploreContextStatusLabel(
  events: StreamEvent[],
  t: (key: string, opts?: Record<string, unknown>) => string,
  isStreaming: boolean,
) {
  if (!isStreaming) return null;
  for (let idx = events.length - 1; idx >= 0; idx -= 1) {
    const event = events[idx];
    const meta = getTraceMeta(event);
    const kind = String(meta.call_kind || "");
    const stage = String(event.stage || meta.phase || "");
    // Anything still inside the explore pre-pass — its reasoning rounds AND the
    // read_source tool calls it fires (stage="context_exploration") — keeps the
    // status on the explore verb, so it doesn't flicker to "Tool Calling…".
    if (kind === "context_exploration" || stage === "context_exploration") {
      return t("Exploring your context…");
    }
    // The answer loop has taken over — let the normal mode label win.
    if (
      kind === "agent_loop_round" ||
      kind === "llm_final_response" ||
      event.type === "tool_call" ||
      event.type === "content"
    ) {
      return null;
    }
  }
  return null;
}

export function StreamingStatus({
  events,
  isStreaming,
  content,
  className = "",
  expandable = false,
  expanded = false,
  onToggle,
  agentName,
  showMark = true,
  traceBounds,
}: {
  events: StreamEvent[];
  isStreaming?: boolean;
  content?: string;
  /** The turn's real span, when ``events`` is only a preview of it. */
  traceBounds?: { started_at?: number | null; ended_at?: number | null } | null;
  // Extra layout classes from the call site (e.g. ``mt-3`` when the row
  // sits at the bottom of the assistant output).
  className?: string;
  // When ``expandable`` the row becomes a disclosure toggle (a trailing
  // chevron rotates with ``expanded``) — used by ``AssistantActivity`` to
  // fold the trace nested beneath it.
  expandable?: boolean;
  expanded?: boolean;
  onToggle?: () => void;
  // Who is doing the thinking — partner chat passes the partner's name so
  // the status reads "Ada Exploring…" instead of the product name.
  agentName?: string;
  // Partner chat shows the partner avatar beside this row, which already
  // signals "who / working", so it hides the activity mark to avoid two
  // icons fighting on one line.
  showMark?: boolean;
}) {
  const { t } = useTranslation();
  const hasFinalContent = Boolean(content && content.trim().length > 0);
  const [nowSeconds, setNowSeconds] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!isStreaming) return;
    const timer = window.setInterval(
      () => setNowSeconds(Date.now() / 1000),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [isStreaming]);

  // Only render once we either have a streaming turn, a completed turn that
  // produced visible content, or a completed turn whose trace is still worth
  // disclosing — empty placeholders (e.g. system message shells) shouldn't
  // show a status row. A turn that ran tools and then ended without a
  // user-facing answer belongs in that third case: dropping the row there
  // also drops the only affordance for opening the trace, so the whole
  // activity block renders as an invisible collapsed shell and the turn looks
  // like it never happened.
  if (!isStreaming && !hasFinalContent && !expandable) return null;
  const mode = detectStreamingMode(
    events,
    hasFinalContent,
    Boolean(isStreaming),
  );

  const name = agentName?.trim() || "DeepTutor";
  let modeLabel = t("{{name}} Reasoning…", { name });
  if (mode === "tool_using") modeLabel = t("Tool Calling…");
  else if (mode === "planning") modeLabel = t("{{name}} Planning…", { name });
  // ``responding`` remains a useful transport/trace distinction, but it is
  // not a second user-facing phase. Keep the one continuous activity surface
  // the conversation already established instead of adding a competing
  // "Responding…" label beside the composer.
  else if (mode === "responding")
    modeLabel = t("{{name}} Exploring…", { name });
  else if (mode === "exploring") modeLabel = t("{{name}} Exploring…", { name });
  else if (mode === "quizzing") modeLabel = t("{{name}} Quizzing…", { name });
  else if (mode === "reflecting")
    modeLabel = t("{{name}} Reflecting…", { name });
  else if (mode === "responded") modeLabel = t("DeepTutor responded.");

  const label =
    getExploreContextStatusLabel(events, t, Boolean(isStreaming)) ??
    getDeepResearchStatusLabel(events, t, Boolean(isStreaming)) ??
    modeLabel;

  // Single turn-level clock. Ticks every second while the turn is in
  // flight and freezes on the final elapsed time once the answer ends —
  // replaces the per-sub-trace duration chips that used to live inside
  // the trace card.
  const turnSeconds = getTurnDurationSeconds(
    events,
    nowSeconds,
    Boolean(isStreaming),
    traceBounds,
  );
  const durationLabel =
    turnSeconds != null ? formatTurnDuration(turnSeconds) : null;
  // Static label after the answer is done — no breathing animation. Every
  // other state is live, so the label breathes to signal ongoing work while
  // the orb beside it runs its own motion.

  return (
    <ActivityHeader
      orb={MODE_TO_ORB[mode]}
      orbSpeed={MODE_SPEED[mode] ?? 1}
      label={label}
      duration={durationLabel}
      settled={mode === "responded"}
      expandable={expandable}
      expanded={expanded}
      onToggle={onToggle}
      showOrb={showMark}
      className={className}
    />
  );
}

/**
 * Whether ``events`` contain at least one renderable trace group — i.e. a
 * call_id whose group is NOT a pure final-response and NOT absorbed into the
 * final answer. Mirrors the gate ``TraceFlow``/``CallTracePanel`` use to
 * decide whether anything will actually render, so callers (e.g. the
 * activity header) can show a disclosure affordance only when there is a
 * trace to disclose.
 */
function hasRenderableCallTrace(events: StreamEvent[]): boolean {
  return selectHasRenderableCallTrace(events);
}

/**
 * Inline trace rows for the assistant message flow: each trace renders as
 * its own one-line, expandable, live-streaming row — there is no outer
 * trace card. Group-level fold (open while working, collapsed once the
 * final answer lands) is handled by ``AssistantActivity``, which nests this
 * directly under the status header.
 */
export function TraceFlow({
  events,
  isStreaming,
}: {
  events: StreamEvent[];
  isStreaming?: boolean;
}) {
  // Mount only when at least one renderable trace group exists — groups
  // that CallTracePanel would discard (final-response only, or reasoning
  // sub-traces absorbed into the final answer) must not leave a stray
  // margin behind.
  const hasCallTrace = useMemo(() => hasRenderableCallTrace(events), [events]);

  if (!hasCallTrace) return null;
  return <CallTracePanel events={events} isStreaming={isStreaming} />;
}

/**
 * Trace rows hanging from the guide line that aligns them under the activity
 * mark, so they read as "nested below" whatever they belong to. Shared by the
 * status header's own trace and by the resumed-round trace the chat surface
 * renders under an ``ask_user`` card.
 */
export function NestedTraceFlow({
  events,
  isStreaming,
}: {
  events: StreamEvent[];
  isStreaming?: boolean;
}) {
  return (
    <div className="pt-2 [&>div]:mb-0">
      <TraceFlow events={events} isStreaming={isStreaming} />
    </div>
  );
}

/**
 * Has the turn entered its final-answer phase? Used to auto-collapse the
 * reasoning trace once DeepTutor stops working and starts (or has finished)
 * its answer.
 *
 *  - turn complete (``!isStreaming``)                    → final
 *  - a pipeline streaming its final write (solve/research) → final
 *    (``detectStreamingMode`` → responding / responded)
 *  - chat single loop: the latest completed round settled as terminal
 *
 * The chat loop streams its final answer as ``agent_loop_round`` content
 * (which ``detectStreamingMode`` reads as "exploring"), so a round's own
 * completion marker — emitted when it lands — is the chat-path signal.
 */
function isChatLoopTurn(events: StreamEvent[]): boolean {
  for (const event of events) {
    if (String(getTraceMeta(event).call_kind || "") === "agent_loop_round") {
      return true;
    }
  }
  return false;
}

/**
 * Whether the most recently *completed* round settled the turn: either a
 * genuinely tool-less ``finish`` round, or a round the backend explicitly
 * marked ``answer_visible`` — mastery's teaching-plus-status-check rounds, a
 * DSML-fallback round, a token-truncated-but-visible round (see
 * ``agent_loop.py``'s completion metadata) all combine tool calls with
 * learner-facing text in the same round, so ``call_role`` never reaches
 * ``"finish"`` for them even though the round is exactly what the trace
 * should collapse for.
 *
 * Looks at only the LATEST completed round, not "has one ever appeared" —
 * a token-truncated round is explicitly non-terminal (the loop keeps
 * writing), so once ITS OWN next round completes, that round's marker
 * supersedes this one and correctly reopens the trace if fresh tool calls
 * are still coming.
 */
function lastRoundSettledFinal(events: StreamEvent[]): boolean {
  for (let idx = events.length - 1; idx >= 0; idx -= 1) {
    const meta = getTraceMeta(events[idx]);
    if (meta.trace_kind === "call_status" && meta.call_state === "complete") {
      return meta.call_role === "finish" || meta.answer_visible === true;
    }
  }
  return false;
}

function isFinalAnswerPhase(
  events: StreamEvent[],
  isStreaming: boolean,
  hasFinalContent: boolean,
): boolean {
  if (!isStreaming) return true;
  if (lastRoundSettledFinal(events)) return true;
  const mode = detectStreamingMode(events, hasFinalContent, true);
  if (mode === "responding" || mode === "responded") {
    // Chat's single loop streams narration text mid-loop, which also reads
    // as "responding" — there only a settled round marker (above) settles
    // the phase; trusting the mode would flap the trace shut on every
    // narration line and open again on the next tool call.
    return !isChatLoopTurn(events);
  }
  return false;
}

/**
 * The assistant activity block: the status header
 * ("DeepTutor Exploring… · 8s", settling to "DeepTutor responded. · 10s")
 * with the exploring trace nested directly beneath it.
 *
 * The trace is expanded by default while DeepTutor is still reasoning /
 * exploring, and collapses once the turn resolves into its final answer.
 * The header doubles as a disclosure toggle, so the user can re-open a
 * collapsed trace (or fold an expanded one) at any time.
 */
/**
 * Shown while a persisted trace is being fetched.
 *
 * The header can now open before its rows exist, so without this the panel
 * would expand onto nothing and read as broken rather than as loading.
 */
function TraceLoadingRow() {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-2 py-1 pl-1 text-xs text-[var(--muted-foreground)]">
      <span className="size-1.5 animate-pulse rounded-full bg-[var(--muted-foreground)]" />
      {t("Loading the full trace…")}
    </div>
  );
}


export function AssistantActivity({
  events,
  traceEvents,
  isStreaming,
  content,
  className = "",
  agentName,
  showMark = true,
  headerClassName = "",
  onTraceToggle,
  traceBounds,
  hasStoredTrace = false,
}: {
  events: StreamEvent[];
  /**
   * The subset of ``events`` whose trace rows belong under this header.
   * Defaults to all of them. The chat surface narrows it to the rounds
   * before the first ``ask_user`` card, because the rounds after one render
   * below that card instead — this block is pinned to the top of the
   * message, so anything appended here after the user answers lands above
   * content they have already read.
   */
  traceEvents?: StreamEvent[];
  isStreaming?: boolean;
  content?: string;
  className?: string;
  /** Forwarded to StreamingStatus — names the thinker in the status row. */
  agentName?: string;
  /** Hide the activity mark (partner chat shows its avatar instead). */
  showMark?: boolean;
  /** Extra classes on the status header row (e.g. a min-height so the row
   *  vertically centers against an adjacent avatar). */
  headerClassName?: string;
  /** Notified when a persisted trace is opened or collapsed. */
  onTraceToggle?: (open: boolean) => void;
  /** The turn's real span, when ``events`` is only a preview of it. */
  traceBounds?: { started_at?: number | null; ended_at?: number | null } | null;
  /**
   * Whether the server still holds trace rows this preview dropped.
   *
   * A finished turn keeps only a compact preview in memory, and that preview
   * discards ``thinking`` — which for a round that called no tools is the
   * entire trace. The header then had nothing renderable, so it rendered as
   * *not expandable*, so the click that would have fetched the full trace
   * could never happen: no rows, therefore no way to ever get rows. This flag
   * breaks that circle by letting the header open on the promise of rows.
   */
  hasStoredTrace?: boolean;
}) {
  const shownTraceEvents = traceEvents ?? events;
  const hasTrace = useMemo(
    () => hasRenderableCallTrace(shownTraceEvents),
    [shownTraceEvents],
  );
  const hasFinalContent = Boolean(content && content.trim().length > 0);
  const finalPhase = useMemo(
    () => isFinalAnswerPhase(events, Boolean(isStreaming), hasFinalContent),
    [events, isStreaming, hasFinalContent],
  );
  // null = follow the phase automatically (open while working, collapsed
  // once answered). A click pins the user's choice for this message.
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  // Openable either because rows are already here, or because the server has
  // rows to hand over once asked. Auto-open still follows the phase only when
  // there is something to show right now: a settled turn stays collapsed until
  // the reader asks for it.
  const expandable = hasTrace || hasStoredTrace;
  const open = expandable && (userOpen ?? (hasTrace && !finalPhase));

  // Match StreamingStatus's own null-guard — it takes ``expandable`` into
  // account for exactly this case, so both surfaces appear or neither does.
  if (!isStreaming && !hasFinalContent && !expandable) return null;

  return (
    <div className={className}>
      <StreamingStatus
        events={events}
        isStreaming={isStreaming}
        content={content}
        expandable={expandable}
        expanded={open}
        onToggle={() => {
          const next = !open;
          setUserOpen(next);
          onTraceToggle?.(next);
        }}
        agentName={agentName}
        showMark={showMark}
        className={headerClassName}
        traceBounds={traceBounds}
      />
      {expandable ? (
        <div
          className={`grid transition-[grid-template-rows,opacity] duration-300 ease-out ${
            open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
          }`}
        >
          <div className="overflow-hidden">
            {/* The trace hangs from a faint guide line aligned under the
                header's activity mark, so it reads as "nested below" the
                status (the elbow/tree language used elsewhere). pt-2 = gap
                below the header when open; [&>div]:mb-0 strips
                CallTracePanel's own bottom margin so the single gap to the
                body comes from this block's outer ``mb-3`` in both states. */}
            {hasTrace ? (
              <NestedTraceFlow
                events={shownTraceEvents}
                isStreaming={isStreaming}
              />
            ) : (
              <TraceLoadingRow />
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  ResearchStagePanel                                                 */
/* ------------------------------------------------------------------ */

function getResearchStageId(event: StreamEvent): ResearchStageCard["id"] {
  const meta = getTraceMeta(event);
  const explicitStage = String(
    (event.metadata as Record<string, unknown> | undefined)
      ?.research_stage_card || "",
  );
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
  const agent = String(
    (event.metadata as Record<string, unknown> | undefined)?.agent_name || "",
  );

  if (stage === "reporting") return "result";
  if (stage === "decomposing" || agent === "decompose_agent")
    return "decompose";
  if (stage === "rephrasing" || agent === "rephrase_agent") return "understand";
  if (stage === "planning") {
    if (text.includes("decompose") || text.includes("queue"))
      return "decompose";
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
  const { t } = useTranslation();
  const cards = useMemo<ResearchStageCard[]>(() => {
    return RESEARCH_STAGE_SPECS.map((spec) => ({
      id: spec.id,
      title: t(spec.titleKey),
      hint: t(spec.hintKey),
      events: events.filter((event) => getResearchStageId(event) === spec.id),
    })).filter((card) => card.events.length > 0);
  }, [events, t]);

  if (!cards.length) return null;

  return (
    <ActivityStack className="mb-3">
      {cards.map((card, index) => {
        const hasTrace = card.events.some((event) =>
          Boolean(getTraceMeta(event).call_id),
        );
        const active =
          Boolean(isStreaming) &&
          index === cards.length - 1 &&
          card.events.some(
            (event) => isTracePending([event]) || event.type === "progress",
          );
        const summary = formatResearchStageSummary(card.events, card.hint);

        return (
          // A research stage is one activity row whose second level is the
          // trace of the calls it made. It used to be a bespoke header with
          // its own spinner beside a separately-rendered trace panel; going
          // through `ActivityRow` means a stage folds, aligns and signals
          // exactly like every other line of work in the product.
          <ActivityRow
            key={card.id}
            state={active ? "running" : "done"}
            title={card.title}
            detail={summary}
            breathing={active}
            followOpen={active}
            autoScrollDetail={active}
          >
            {hasTrace ? (
              <CallTracePanel events={card.events} isStreaming={isStreaming} />
            ) : null}
          </ActivityRow>
        );
      })}
    </ActivityStack>
  );
}
