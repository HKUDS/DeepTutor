"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BrainCircuit,
  ChevronDown,
  Check,
  Code2,
  Database,
  FileText,
  FileSearch,
  Globe,
  Lightbulb,
  Loader2,
  MessageSquare,
  Microscope,
  PenLine,
  Play,
  Sparkles,
  Terminal,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiUrl } from "@/lib/api";
import AssistantResponse from "@/components/common/AssistantResponse";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import ProcessLogs from "@/components/common/ProcessLogs";
import ResearchConfigPanel from "@/components/research/ResearchConfigPanel";
import { extractBase64FromDataUrl, readFileAsDataUrl } from "@/lib/file-attachments";
import { listKnowledgeBases } from "@/lib/knowledge-api";
import type { StreamEvent } from "@/lib/unified-ws";
import {
  filterFrontendTools,
  FRONTEND_HIDDEN_TOOLS,
  loadCapabilityPlaygroundConfigs,
  resolveCapabilityPlaygroundConfig,
  saveCapabilityPlaygroundConfig,
  type CapabilityPlaygroundConfig,
  type CapabilityPlaygroundConfigMap,
} from "@/lib/playground-config";
import {
  buildResearchWSConfig,
  createEmptyResearchConfig,
  normalizeResearchConfig,
  validateResearchConfig,
  type DeepResearchFormConfig,
  type ResearchSource,
} from "@/lib/research-types";

/* ------------------------------------------------------------------ */
/*  Icon maps — consistent with chat page                              */
/* ------------------------------------------------------------------ */

const TOOL_ICONS: Record<string, LucideIcon> = {
  brainstorm: Lightbulb,
  rag: Database,
  web_search: Globe,
  code_execution: Code2,
  reason: Sparkles,
  paper_search: FileSearch,
};

const TOOL_LABELS: Record<string, string> = {
  brainstorm: "Brainstorm",
  rag: "RAG",
  web_search: "Web Search",
  code_execution: "Code Execution",
  reason: "Reason",
  paper_search: "Arxiv Search",
};

const RESEARCH_SOURCE_OPTIONS: Array<{ name: ResearchSource; label: string; icon: LucideIcon }> = [
  { name: "kb", label: "Knowledge Base", icon: Database },
  { name: "web", label: "Web", icon: Globe },
  { name: "papers", label: "Papers", icon: FileSearch },
];

const CAPABILITY_ICONS: Record<string, LucideIcon> = {
  chat: MessageSquare,
  deep_solve: BrainCircuit,
  deep_question: PenLine,
  deep_research: Microscope,
};

const CAPABILITY_LABELS: Record<string, string> = {
  chat: "Chat",
  deep_solve: "Deep Solve",
  deep_question: "Quiz Generation",
  deep_research: "Deep Research",
};

function getToolIcon(name: string): LucideIcon {
  return TOOL_ICONS[name] ?? Terminal;
}

function getCapIcon(name: string): LucideIcon {
  return CAPABILITY_ICONS[name] ?? Sparkles;
}

function getToolLabel(name: string): string {
  return TOOL_LABELS[name] ?? titleCase(name);
}

function getCapabilityLabel(name: string): string {
  return CAPABILITY_LABELS[name] ?? titleCase(name);
}

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ToolParam {
  name: string;
  type: string;
  description?: string;
  required?: boolean;
  default?: unknown;
  enum?: string[] | null;
}

interface ToolInfo {
  name: string;
  description: string;
  parameters?: ToolParam[];
}

interface CapabilityInfo {
  name: string;
  description: string;
  stages?: string[];
  tools_used?: string[];
}

interface ExecResult {
  success: boolean;
  content: string;
  sources: Array<Record<string, string>>;
  metadata: Record<string, unknown>;
}

interface CapabilityExecResult {
  success: boolean;
  data: Record<string, unknown>;
  elapsedMs?: number;
}

interface KnowledgeBase {
  name: string;
  is_default?: boolean;
}

interface TesterMessage {
  role: "user" | "assistant";
  content: string;
  events?: StreamEvent[];
  processLogs?: string[];
  result?: CapabilityExecResult | null;
  error?: string | null;
}

type DeepQuestionMode = "custom" | "mimic";

interface DeepQuestionFormConfig {
  mode: DeepQuestionMode;
  topic: string;
  num_questions: number;
  difficulty: string;
  question_type: string;
  preference: string;
  paper_path: string;
  max_questions: number;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function titleCase(v: string) {
  return v.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const QUERY_PARAM_NAMES = new Set(["query", "intent", "code", "topic"]);

const DEFAULT_DEEP_QUESTION_CONFIG: DeepQuestionFormConfig = {
  mode: "custom",
  topic: "",
  num_questions: 3,
  difficulty: "auto",
  question_type: "auto",
  preference: "",
  paper_path: "",
  max_questions: 10,
};

function normalizeDeepQuestionConfig(
  raw: Record<string, unknown> | undefined,
): DeepQuestionFormConfig {
  const mode = raw?.mode === "mimic" ? "mimic" : "custom";
  return {
    mode,
    topic: typeof raw?.topic === "string" ? raw.topic : "",
    num_questions:
      typeof raw?.num_questions === "number" && raw.num_questions > 0
        ? raw.num_questions
        : DEFAULT_DEEP_QUESTION_CONFIG.num_questions,
    difficulty:
      typeof raw?.difficulty === "string" && raw.difficulty
        ? raw.difficulty
        : DEFAULT_DEEP_QUESTION_CONFIG.difficulty,
    question_type:
      typeof raw?.question_type === "string" && raw.question_type
        ? raw.question_type
        : DEFAULT_DEEP_QUESTION_CONFIG.question_type,
    preference: typeof raw?.preference === "string" ? raw.preference : "",
    paper_path: typeof raw?.paper_path === "string" ? raw.paper_path : "",
    max_questions:
      typeof raw?.max_questions === "number" && raw.max_questions > 0
        ? raw.max_questions
        : DEFAULT_DEEP_QUESTION_CONFIG.max_questions,
  };
}

/* ------------------------------------------------------------------ */
/*  TracePanel                                                         */
/* ------------------------------------------------------------------ */

function TracePanel({ events }: { events: StreamEvent[] }) {
  const { t } = useTranslation();
  if (!events.length) return null;

  const grouped = new Map<string, StreamEvent[]>();
  for (const ev of events) {
    const key = ev.stage || "session";
    const list = grouped.get(key) ?? [];
    list.push(ev);
    grouped.set(key, list);
  }

  return (
    <div className="space-y-2">
      {Array.from(grouped.entries()).map(([stage, stageEvents]) => {
        const renderable = stageEvents.filter((e) =>
          ["thinking", "progress", "tool_call", "tool_result", "error"].includes(e.type),
        );
        if (!renderable.length) return null;
        return (
          <details key={stage} className="group overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--card)]">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-[13px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/50">
              <span>{stage === "session" ? t("Details") : titleCase(stage)}</span>
              <ChevronDown size={13} className="text-[var(--muted-foreground)] transition-transform group-open:rotate-180" />
            </summary>
            <div className="border-t border-[var(--border)] px-3 py-2.5 space-y-1.5">
              {renderable.map((ev, i) => {
                if (ev.type === "thinking") return <p key={`${stage}-t-${i}`} className="text-[12px] italic leading-relaxed text-[var(--muted-foreground)]">{ev.content}</p>;
                if (ev.type === "progress") {
                  const cur = Number(ev.metadata?.current ?? 0), tot = Number(ev.metadata?.total ?? 0);
                  return (
                    <div key={`${stage}-p-${i}`} className="rounded-md bg-[var(--muted)] px-2.5 py-1.5 text-[12px] text-[var(--muted-foreground)]">
                      <div>{ev.content}</div>
                      {tot > 0 && <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-[var(--border)]"><div className="h-full rounded-full bg-[var(--primary)] transition-all duration-300" style={{ width: `${Math.min(100, (cur / tot) * 100)}%` }} /></div>}
                    </div>
                  );
                }
                if (ev.type === "tool_call" || ev.type === "tool_result") return (
                  <div key={`${stage}-tc-${i}`} className="rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5">
                    <div className="text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">{ev.type === "tool_call" ? t("Tool call") : t("Tool result")}</div>
                    <div className="mt-0.5 text-[12px] text-[var(--foreground)]">{ev.content || String(ev.metadata?.tool ?? "")}</div>
                  </div>
                );
                if (ev.type === "error") return <div key={`${stage}-e-${i}`} className="rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">{ev.content}</div>;
                return null;
              })}
            </div>
          </details>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  ToolExecutor                                                       */
/* ------------------------------------------------------------------ */

function ToolExecutor({ tool, knowledgeBases }: { tool: ToolInfo; knowledgeBases: KnowledgeBase[] }) {
  const { t } = useTranslation();
  const params = tool.parameters ?? [];
  const [values, setValues] = useState<Record<string, string>>({});
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<ExecResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [processLogs, setProcessLogs] = useState<string[]>([]);

  useEffect(() => {
    setValues({});
    setResult(null);
    setError(null);
    setProcessLogs([]);
  }, [tool.name]);

  const setParam = (name: string, val: string) => setValues((p) => ({ ...p, [name]: val }));

  const queryParam = params.find((p) => QUERY_PARAM_NAMES.has(p.name));
  const otherParams = params.filter((p) => !QUERY_PARAM_NAMES.has(p.name));

  const execute = async () => {
    setExecuting(true);
    setResult(null);
    setError(null);
    setProcessLogs([]);
    try {
      const coerced: Record<string, unknown> = {};
      for (const p of params) {
        const raw = values[p.name];
        if (!raw) continue;
        if (p.type === "integer") coerced[p.name] = parseInt(raw, 10);
        else if (p.type === "number") coerced[p.name] = parseFloat(raw);
        else if (p.type === "boolean") coerced[p.name] = raw === "true";
        else coerced[p.name] = raw;
      }

      const res = await fetch(apiUrl(`/api/v1/plugins/tools/${tool.name}/execute-stream`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ params: coerced }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          if (!part.trim()) continue;
          const eventMatch = part.match(/^event:\s*(.+)$/m);
          const dataMatch = part.match(/^data:\s*(.+)$/m);
          if (!eventMatch || !dataMatch) continue;

          const eventType = eventMatch[1].trim();
          let payload: Record<string, unknown>;
          try { payload = JSON.parse(dataMatch[1]); } catch { continue; }

          if (eventType === "log") {
            const line = (payload.line as string) ?? "";
            setProcessLogs((prev) => [...prev, line]);
          } else if (eventType === "result") {
            setResult({
              success: payload.success as boolean,
              content: (payload.content as string) ?? "",
              sources: (payload.sources as Array<Record<string, string>>) ?? [],
              metadata: (payload.metadata as Record<string, unknown>) ?? {},
            });
          } else if (eventType === "error") {
            setError((payload.detail as string) ?? "Unknown error");
          }
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExecuting(false);
    }
  };

  const isKbNameParam = (p: ToolParam) => p.name === "kb_name";

  const renderParam = (p: ToolParam) => {
    if (isKbNameParam(p)) {
      return (
        <select
          value={values[p.name] ?? ""}
          onChange={(e) => setParam(p.name, e.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/40"
        >
          <option value="">{t("Select knowledge base...")}</option>
          {knowledgeBases.map((kb) => <option key={kb.name} value={kb.name}>{kb.name}{kb.is_default ? ` (${t("default")})` : ""}</option>)}
        </select>
      );
    }

    if (p.enum) {
      return (
        <select
          value={values[p.name] ?? ""}
          onChange={(e) => setParam(p.name, e.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/40"
        >
          <option value="">{t("Select...")}</option>
          {p.enum.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      );
    }

    return (
      <input
        type={p.type === "integer" || p.type === "number" ? "number" : "text"}
        value={values[p.name] ?? ""}
        onChange={(e) => setParam(p.name, e.target.value)}
        placeholder={p.description || p.name}
        className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--primary)]/40 placeholder:text-[var(--muted-foreground)]"
      />
    );
  };

  return (
    <div className="space-y-5">
      {/* Config params (non-query) */}
      {otherParams.length > 0 && (
        <div>
          <h4 className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--muted-foreground)]">{t("Parameters")}</h4>
          <div className="grid gap-3 md:grid-cols-2">
            {otherParams.map((p) => (
              <div key={`${tool.name}-${p.name}`}>
                <label className="mb-1 block text-[12px] font-medium text-[var(--foreground)]">
                  {p.name}
                  {p.required !== false && <span className="ml-0.5 text-[var(--primary)]">*</span>}
                  <span className="ml-1.5 text-[10px] font-normal uppercase text-[var(--muted-foreground)]">{p.type}</span>
                </label>
                {renderParam(p)}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Query input — visually distinct */}
      {queryParam && (
        <div className="rounded-xl border-2 border-dashed border-[var(--primary)]/30 bg-[var(--primary)]/[0.03] p-4">
          <label className="mb-2 flex items-center gap-1.5 text-[12px] font-semibold text-[var(--primary)]">
            <Terminal size={13} />
            {queryParam.name === "code" ? t("Code input") : t("Query input")}
          </label>
          {queryParam.name === "code" || queryParam.name === "topic" ? (
            <textarea
              value={values[queryParam.name] ?? ""}
              onChange={(e) => setParam(queryParam.name, e.target.value)}
              placeholder={queryParam.description || t("Enter your input...")}
              rows={queryParam.name === "topic" ? 5 : 4}
              className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 font-mono text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--primary)]/40 placeholder:text-[var(--muted-foreground)]"
            />
          ) : (
            <input
              type="text"
              value={values[queryParam.name] ?? ""}
              onChange={(e) => setParam(queryParam.name, e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !executing) execute(); }}
              placeholder={queryParam.description || t("Enter your query...")}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[14px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--primary)]/40 placeholder:text-[var(--muted-foreground)]"
            />
          )}
        </div>
      )}

      {/* Execute button */}
      <button
        onClick={execute}
        disabled={executing}
        className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 py-2 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity disabled:opacity-50"
      >
        {executing ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
        {executing ? t("Running...") : t("Execute")}
      </button>

      {/* Process Logs */}
      <ProcessLogs logs={processLogs} executing={executing} />

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            {result.success ? (
              <span className="inline-flex items-center gap-1 rounded-md bg-green-50 px-2 py-0.5 text-[11px] font-medium text-green-700 dark:bg-green-950/30 dark:text-green-400">
                <Check size={10} /> {t("Success")}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-md bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700 dark:bg-red-950/30 dark:text-red-400">
                <X size={10} /> {t("Failed")}
              </span>
            )}
          </div>

          {result.content && (
            <div className="max-h-[400px] overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--background)] p-4">
              <MarkdownRenderer content={result.content} variant="prose" />
            </div>
          )}

          {result.sources.length > 0 && (
            <details className="group rounded-lg border border-[var(--border)] bg-[var(--card)]">
              <summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2 text-[13px] font-medium text-[var(--foreground)]">
                {t("Sources")} ({result.sources.length})
                <ChevronDown size={13} className="text-[var(--muted-foreground)] transition-transform group-open:rotate-180" />
              </summary>
              <div className="border-t border-[var(--border)] px-3 py-2.5 space-y-1.5">
                {result.sources.map((s, i) => (
                  <div key={`src-${i}`} className="rounded-md bg-[var(--muted)] px-2.5 py-1.5 text-[12px]">
                    <div className="font-medium text-[var(--foreground)]">{s.title || s.query || s.type || t("Source")}</div>
                    {s.url && <div className="mt-0.5 break-all text-[11px] text-[var(--muted-foreground)]">{s.url}</div>}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  CapabilityResultPanel                                              */
/* ------------------------------------------------------------------ */

function CapabilityResultPanel({ result }: { result: CapabilityExecResult | null | undefined }) {
  const { t } = useTranslation();
  if (!result) return null;

  const response = typeof result.data.response === "string" ? result.data.response : "";
  const extraData = Object.fromEntries(
    Object.entries(result.data).filter(([key]) => key !== "response"),
  );
  const extraKeys = Object.keys(extraData);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {result.success ? (
          <span className="inline-flex items-center gap-1 rounded-md bg-green-50 px-2 py-0.5 text-[11px] font-medium text-green-700 dark:bg-green-950/30 dark:text-green-400">
            <Check size={10} /> {t("Success")}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-md bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700 dark:bg-red-950/30 dark:text-red-400">
            <X size={10} /> {t("Failed")}
          </span>
        )}
        {typeof result.elapsedMs === "number" && (
          <span className="text-[11px] text-[var(--muted-foreground)]">
            {result.elapsedMs} ms
          </span>
        )}
      </div>

      {response && (
        <div className="max-h-[400px] overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--background)] p-4">
          <MarkdownRenderer content={response} variant="prose" />
        </div>
      )}

      {!response && extraKeys.length > 0 && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
          <pre className="overflow-x-auto whitespace-pre-wrap break-all text-[12px] text-[var(--muted-foreground)]">
            {JSON.stringify(extraData, null, 2)}
          </pre>
        </div>
      )}

      {extraKeys.length > 0 && response && (
        <details className="group rounded-lg border border-[var(--border)] bg-[var(--card)]">
          <summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2 text-[13px] font-medium text-[var(--foreground)]">
            {t("Metadata")}
            <ChevronDown size={13} className="text-[var(--muted-foreground)] transition-transform group-open:rotate-180" />
          </summary>
          <div className="border-t border-[var(--border)] px-3 py-2.5">
            <pre className="overflow-x-auto whitespace-pre-wrap break-all text-[12px] text-[var(--muted-foreground)]">
              {JSON.stringify(extraData, null, 2)}
            </pre>
          </div>
        </details>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  DeepQuestionTester                                                 */
/* ------------------------------------------------------------------ */

function DeepQuestionTester({
  capability,
  enabledTools,
  knowledgeBase,
  config,
  onConfigChange,
}: {
  capability: CapabilityInfo;
  enabledTools: string[];
  knowledgeBase: string;
  config: DeepQuestionFormConfig;
  onConfigChange: (next: DeepQuestionFormConfig) => void;
}) {
  const { t, i18n } = useTranslation();
  const [messages, setMessages] = useState<TesterMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [uploadedPdf, setUploadedPdf] = useState<File | null>(null);

  const updateLastAssistant = (updater: (msg: TesterMessage) => TesterMessage) => {
    setMessages((prev) => {
      const msgs = [...prev];
      const last = msgs[msgs.length - 1];
      if (last?.role !== "assistant") return prev;
      msgs[msgs.length - 1] = updater(last);
      return msgs;
    });
  };

  const updateConfig = <K extends keyof DeepQuestionFormConfig>(
    key: K,
    value: DeepQuestionFormConfig[K],
  ) => {
    onConfigChange({ ...config, [key]: value });
  };

  const fileToAttachment = async (file: File) => {
    const dataUrl = await readFileAsDataUrl(file);
    return {
      type: "pdf",
      filename: file.name,
      mime_type: file.type || "application/pdf",
      base64: extractBase64FromDataUrl(dataUrl),
    };
  };

  const canRun =
    config.mode === "custom"
      ? config.topic.trim().length > 0
      : Boolean(uploadedPdf) || config.paper_path.trim().length > 0;

  const run = async () => {
    if (!canRun || streaming) return;

    const userContent =
      config.mode === "custom"
        ? config.topic.trim()
        : uploadedPdf
          ? `Mimic questions from uploaded paper: ${uploadedPdf.name}`
          : `Mimic questions from parsed paper: ${config.paper_path.trim()}`;

    setMessages((prev) => [
      ...prev,
      { role: "user", content: userContent },
      { role: "assistant", content: "", events: [], processLogs: [], result: null, error: null },
    ]);
    setStreaming(true);

    try {
      const attachments =
        config.mode === "mimic" && uploadedPdf ? [await fileToAttachment(uploadedPdf)] : [];

      const requestConfig =
        config.mode === "custom"
          ? {
              mode: "custom",
              topic: config.topic.trim(),
              num_questions: config.num_questions,
              difficulty: config.difficulty === "auto" ? "" : config.difficulty,
              question_type: config.question_type === "auto" ? "" : config.question_type,
              preference: config.preference.trim(),
            }
          : {
              mode: "mimic",
              paper_path: uploadedPdf ? "" : config.paper_path.trim(),
              max_questions: config.max_questions,
            };

      const res = await fetch(
        apiUrl(`/api/v1/plugins/capabilities/${capability.name}/execute-stream`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            content: userContent,
            tools: enabledTools,
            knowledge_bases: enabledTools.includes("rag") && knowledgeBase ? [knowledgeBase] : [],
            language: i18n.language,
            config: requestConfig,
            attachments,
          }),
        },
      );

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          if (!part.trim()) continue;
          const eventMatch = part.match(/^event:\s*(.+)$/m);
          const dataMatch = part.match(/^data:\s*(.+)$/m);
          if (!eventMatch || !dataMatch) continue;

          const eventType = eventMatch[1].trim();
          let payload: Record<string, unknown>;
          try {
            payload = JSON.parse(dataMatch[1]);
          } catch {
            continue;
          }

          if (eventType === "log") {
            const line = (payload.line as string) ?? "";
            updateLastAssistant((last) => ({
              ...last,
              processLogs: [...(last.processLogs || []), line],
            }));
            continue;
          }

          if (eventType === "stream") {
            const event = payload as unknown as StreamEvent;
            if (event.type === "session" || event.type === "done") continue;
            updateLastAssistant((last) => ({
              ...last,
              content: event.type === "content" ? `${last.content}${event.content}` : last.content,
              events: [...(last.events || []), event],
            }));
            continue;
          }

          if (eventType === "result") {
            updateLastAssistant((last) => ({
              ...last,
              result: {
                success: Boolean(payload.success),
                data: ((payload.data as Record<string, unknown>) ?? {}),
                elapsedMs: typeof payload.elapsed_ms === "number" ? payload.elapsed_ms : undefined,
              },
            }));
            continue;
          }

          if (eventType === "error") {
            updateLastAssistant((last) => ({
              ...last,
              error: (payload.detail as string) ?? "Unknown error",
            }));
          }
        }
      }
    } catch (err: unknown) {
      updateLastAssistant((last) => ({
        ...last,
        error: err instanceof Error ? err.message : String(err),
      }));
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
        <div className="mb-3 flex flex-wrap gap-2">
          <button
            onClick={() => updateConfig("mode", "custom")}
            className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
              config.mode === "custom"
                ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                : "bg-[var(--muted)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            {t("Custom")}
          </button>
          <button
            onClick={() => updateConfig("mode", "mimic")}
            className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
              config.mode === "mimic"
                ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                : "bg-[var(--muted)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            {t("Mimic Exam")}
          </button>
        </div>

        {config.mode === "custom" ? (
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--foreground)]">
                {t("Topic")}
              </label>
              <textarea
                value={config.topic}
                onChange={(e) => updateConfig("topic", e.target.value)}
                rows={3}
                placeholder={t("e.g. Gradient Descent Optimization")}
                className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--primary)]/40 placeholder:text-[var(--muted-foreground)]"
              />
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <div>
                <label className="mb-1 block text-[12px] font-medium text-[var(--foreground)]">
                  {t("Count")}
                </label>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={config.num_questions}
                  onChange={(e) => updateConfig("num_questions", Math.max(1, Number(e.target.value) || 1))}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/40"
                />
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-medium text-[var(--foreground)]">
                  {t("Difficulty")}
                </label>
                <select
                  value={config.difficulty}
                  onChange={(e) => updateConfig("difficulty", e.target.value)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/40"
                >
                  <option value="auto">{t("Auto")}</option>
                  <option value="easy">{t("Easy")}</option>
                  <option value="medium">{t("Medium")}</option>
                  <option value="hard">{t("Hard")}</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-medium text-[var(--foreground)]">
                  {t("Type")}
                </label>
                <select
                  value={config.question_type}
                  onChange={(e) => updateConfig("question_type", e.target.value)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/40"
                >
                  <option value="auto">{t("Auto")}</option>
                  <option value="choice">{t("Multiple Choice")}</option>
                  <option value="written">{t("Written")}</option>
                  <option value="coding">{t("Coding")}</option>
                </select>
              </div>
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--foreground)]">
                {t("Preference")}
              </label>
              <textarea
                value={config.preference}
                onChange={(e) => updateConfig("preference", e.target.value)}
                rows={3}
                placeholder={t("Extra constraints, style, focus areas...")}
                className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--primary)]/40 placeholder:text-[var(--muted-foreground)]"
              />
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--foreground)]">
                {t("Upload Exam Paper (PDF)")}
              </label>
              <label className="flex cursor-pointer items-center justify-center gap-2 rounded-xl border-2 border-dashed border-[var(--border)] bg-[var(--card)] px-4 py-6 text-[13px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--primary)]/40 hover:text-[var(--foreground)]">
                <Upload size={16} />
                <span>{uploadedPdf ? uploadedPdf.name : t("Click to upload PDF")}</span>
                <input
                  type="file"
                  accept=".pdf,application/pdf"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0] ?? null;
                    setUploadedPdf(file);
                    if (file) updateConfig("paper_path", "");
                  }}
                />
              </label>
            </div>
            <div className="text-center text-[11px] uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
              {t("Or")}
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium text-[var(--foreground)]">
                {t("Pre-parsed Directory")}
              </label>
              <div className="relative">
                <FileText size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]" />
                <input
                  type="text"
                  value={config.paper_path}
                  onChange={(e) => {
                    setUploadedPdf(null);
                    updateConfig("paper_path", e.target.value);
                  }}
                  placeholder={t("e.g. 2211asm1")}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] py-2 pl-9 pr-3 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--primary)]/40 placeholder:text-[var(--muted-foreground)]"
                />
              </div>
            </div>
            <div className="max-w-xs">
              <label className="mb-1 block text-[12px] font-medium text-[var(--foreground)]">
                {t("Max Questions")}
              </label>
              <input
                type="number"
                min={1}
                max={100}
                value={config.max_questions}
                onChange={(e) => updateConfig("max_questions", Math.max(1, Number(e.target.value) || 1))}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/40"
              />
            </div>
          </div>
        )}
      </div>

      {messages.map((msg, i) => (
        <div key={`${msg.role}-${i}`}>
          <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
            {msg.role === "user" ? t("You") : t("Assistant")}
          </div>
          {msg.role === "user" ? (
            <div className="rounded-lg bg-[var(--muted)] px-3 py-2 text-[13px] text-[var(--foreground)]">{msg.content}</div>
          ) : (
            <div className="space-y-2">
              <TracePanel events={msg.events || []} />
              <ProcessLogs
                logs={msg.processLogs || []}
                executing={streaming && i === messages.length - 1}
                title={t("Process")}
              />
              {msg.error && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                  {msg.error}
                </div>
              )}
              <AssistantResponse
                content={msg.content}
                className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2.5"
              />
              <CapabilityResultPanel result={msg.result} />
            </div>
          )}
        </div>
      ))}

      <div className="flex justify-end">
        <button
          onClick={run}
          disabled={!canRun || streaming}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {streaming ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {streaming ? t("Running...") : t("Generate")}
        </button>
      </div>
    </div>
  );
}

function DeepResearchTester({
  capability,
  enabledTools,
  knowledgeBase,
  config,
  onConfigChange,
}: {
  capability: CapabilityInfo;
  enabledTools: string[];
  knowledgeBase: string;
  config: DeepResearchFormConfig;
  onConfigChange: (next: DeepResearchFormConfig) => void;
}) {
  const { t, i18n } = useTranslation();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<TesterMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const validation = useMemo(() => validateResearchConfig(config), [config]);

  const updateLastAssistant = (updater: (msg: TesterMessage) => TesterMessage) => {
    setMessages((prev) => {
      const msgs = [...prev];
      const last = msgs[msgs.length - 1];
      if (last?.role !== "assistant") return prev;
      msgs[msgs.length - 1] = updater(last);
      return msgs;
    });
  };

  const run = async () => {
    const content = input.trim();
    if (!content || streaming || !validation.valid) return;
    setMessages((prev) => [
      ...prev,
      { role: "user", content },
      { role: "assistant", content: "", events: [], processLogs: [], result: null, error: null },
    ]);
    setStreaming(true);

    try {
      const res = await fetch(
        apiUrl(`/api/v1/plugins/capabilities/${capability.name}/execute-stream`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            content,
            tools: enabledTools,
            knowledge_bases: config.sources.includes("kb") && knowledgeBase ? [knowledgeBase] : [],
            language: i18n.language,
            config: buildResearchWSConfig(config),
          }),
        },
      );

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          if (!part.trim()) continue;
          const eventMatch = part.match(/^event:\s*(.+)$/m);
          const dataMatch = part.match(/^data:\s*(.+)$/m);
          if (!eventMatch || !dataMatch) continue;

          const eventType = eventMatch[1].trim();
          let payload: Record<string, unknown>;
          try {
            payload = JSON.parse(dataMatch[1]);
          } catch {
            continue;
          }

          if (eventType === "log") {
            const line = (payload.line as string) ?? "";
            updateLastAssistant((last) => ({
              ...last,
              processLogs: [...(last.processLogs || []), line],
            }));
            continue;
          }

          if (eventType === "stream") {
            const event = payload as unknown as StreamEvent;
            if (event.type === "session" || event.type === "done") continue;
            updateLastAssistant((last) => ({
              ...last,
              content: event.type === "content" ? `${last.content}${event.content}` : last.content,
              events: [...(last.events || []), event],
            }));
            continue;
          }

          if (eventType === "result") {
            updateLastAssistant((last) => ({
              ...last,
              result: {
                success: Boolean(payload.success),
                data: ((payload.data as Record<string, unknown>) ?? {}),
                elapsedMs: typeof payload.elapsed_ms === "number" ? payload.elapsed_ms : undefined,
              },
            }));
            continue;
          }

          if (eventType === "error") {
            updateLastAssistant((last) => ({
              ...last,
              error: (payload.detail as string) ?? "Unknown error",
            }));
          }
        }
      }
    } catch (err: unknown) {
      updateLastAssistant((last) => ({
        ...last,
        error: err instanceof Error ? err.message : String(err),
      }));
    } finally {
      setStreaming(false);
    }
  };

  const toggleSource = (source: ResearchSource) => {
    onConfigChange({
      ...config,
      sources: config.sources.includes(source)
        ? config.sources.filter((item) => item !== source)
        : [...config.sources, source],
    });
  };

  return (
    <div className="space-y-4">
      <ResearchConfigPanel
        value={config}
        errors={validation.errors}
        collapsed={false}
        onChange={onConfigChange}
        onToggleCollapsed={() => {}}
      />
      <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
        <div className="mb-2 text-[12px] font-medium text-[var(--foreground)]">{t("Sources")}</div>
        <div className="flex flex-wrap gap-2">
          {RESEARCH_SOURCE_OPTIONS.map((source) => {
            const active = config.sources.includes(source.name);
            const Icon = source.icon;
            return (
              <button
                key={source.name}
                type="button"
                onClick={() => toggleSource(source.name)}
                className={`inline-flex h-[32px] items-center gap-1.5 rounded-full px-3 text-[12px] font-medium transition-[background-color,color,box-shadow] ${
                  active
                    ? "bg-[var(--muted)] text-[var(--foreground)] shadow-[0_1px_2px_rgba(15,23,42,0.05)] ring-1 ring-[var(--border)]/55"
                    : "text-[var(--muted-foreground)]/75 hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
                }`}
              >
                <Icon size={13} strokeWidth={1.7} />
                {t(source.label)}
              </button>
            );
          })}
        </div>
        <div className="mt-2 text-[11px] text-[var(--muted-foreground)]">
          {config.sources.length
            ? t("Selected sources will be queried during research.")
            : t("No source selected: the run will use llm-only research.")}
        </div>
      </div>
      <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(); } }}
          rows={3}
          placeholder={t("Describe the research topic...")}
          className="w-full resize-none bg-transparent text-[13px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
        />
        <div className="mt-2 flex justify-end">
          <button
            onClick={run}
            disabled={!input.trim() || streaming || !validation.valid}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {streaming ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
            {streaming ? t("Running...") : t("Run Research")}
          </button>
        </div>
      </div>

      {messages.map((msg, i) => (
        <div key={`${msg.role}-${i}`}>
          <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
            {msg.role === "user" ? t("You") : t("Assistant")}
          </div>
          {msg.role === "user" ? (
            <div className="rounded-lg bg-[var(--muted)] px-3 py-2 text-[13px] text-[var(--foreground)]">{msg.content}</div>
          ) : (
            <div className="space-y-2">
              <TracePanel events={msg.events || []} />
              <ProcessLogs
                logs={msg.processLogs || []}
                executing={streaming && i === messages.length - 1}
                title={t("Process")}
              />
              {msg.error && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                  {msg.error}
                </div>
              )}
              <AssistantResponse
                content={msg.content}
                className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2.5"
              />
              <CapabilityResultPanel result={msg.result} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  CapabilityTester                                                   */
/* ------------------------------------------------------------------ */

function CapabilityTester({
  capability,
  enabledTools,
  knowledgeBase,
}: {
  capability: CapabilityInfo;
  enabledTools: string[];
  knowledgeBase: string;
}) {
  const { t, i18n } = useTranslation();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<TesterMessage[]>([]);
  const [streaming, setStreaming] = useState(false);

  const updateLastAssistant = (updater: (msg: TesterMessage) => TesterMessage) => {
    setMessages((prev) => {
      const msgs = [...prev];
      const last = msgs[msgs.length - 1];
      if (last?.role !== "assistant") return prev;
      msgs[msgs.length - 1] = updater(last);
      return msgs;
    });
  };

  const send = async () => {
    const content = input.trim();
    if (!content || streaming) return;
    setMessages((prev) => [
      ...prev,
      { role: "user", content },
      { role: "assistant", content: "", events: [], processLogs: [], result: null, error: null },
    ]);
    setInput("");
    setStreaming(true);

    try {
      const res = await fetch(
        apiUrl(`/api/v1/plugins/capabilities/${capability.name}/execute-stream`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            content,
            tools: enabledTools,
            knowledge_bases: enabledTools.includes("rag") && knowledgeBase ? [knowledgeBase] : [],
            language: i18n.language,
          }),
        },
      );

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || `HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          if (!part.trim()) continue;
          const eventMatch = part.match(/^event:\s*(.+)$/m);
          const dataMatch = part.match(/^data:\s*(.+)$/m);
          if (!eventMatch || !dataMatch) continue;

          const eventType = eventMatch[1].trim();
          let payload: Record<string, unknown>;
          try {
            payload = JSON.parse(dataMatch[1]);
          } catch {
            continue;
          }

          if (eventType === "log") {
            const line = (payload.line as string) ?? "";
            updateLastAssistant((last) => ({
              ...last,
              processLogs: [...(last.processLogs || []), line],
            }));
            continue;
          }

          if (eventType === "stream") {
            const event = payload as unknown as StreamEvent;
            if (event.type === "session" || event.type === "done") continue;
            updateLastAssistant((last) => ({
              ...last,
              content: event.type === "content" ? `${last.content}${event.content}` : last.content,
              events: [...(last.events || []), event],
            }));
            continue;
          }

          if (eventType === "result") {
            updateLastAssistant((last) => ({
              ...last,
              result: {
                success: Boolean(payload.success),
                data: ((payload.data as Record<string, unknown>) ?? {}),
                elapsedMs: typeof payload.elapsed_ms === "number" ? payload.elapsed_ms : undefined,
              },
            }));
            continue;
          }

          if (eventType === "error") {
            updateLastAssistant((last) => ({
              ...last,
              error: (payload.detail as string) ?? "Unknown error",
            }));
          }
        }
      }
    } catch (err: unknown) {
      updateLastAssistant((last) => ({
        ...last,
        error: err instanceof Error ? err.message : String(err),
      }));
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div className="space-y-3">
      {messages.map((msg, i) => (
        <div key={`${msg.role}-${i}`}>
          <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
            {msg.role === "user" ? t("You") : t("Assistant")}
          </div>
          {msg.role === "user" ? (
            <div className="rounded-lg bg-[var(--muted)] px-3 py-2 text-[13px] text-[var(--foreground)]">{msg.content}</div>
          ) : (
            <div className="space-y-2">
              <TracePanel events={msg.events || []} />
              <ProcessLogs
                logs={msg.processLogs || []}
                executing={streaming && i === messages.length - 1}
                title={t("Process")}
              />
              {msg.error && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                  {msg.error}
                </div>
              )}
              <AssistantResponse
                content={msg.content}
                className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2.5"
              />
              <CapabilityResultPanel result={msg.result} />
            </div>
          )}
        </div>
      ))}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          rows={2}
          placeholder={`${t("Try")} ${t(getCapabilityLabel(capability.name))}...`}
          className="w-full resize-none bg-transparent text-[13px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
        />
        <div className="mt-2 flex justify-end">
          <button
            onClick={send}
            disabled={!input.trim() || streaming}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {streaming ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
            {streaming ? t("Running...") : t("Send")}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Page                                                          */
/* ------------------------------------------------------------------ */

export default function PlaygroundPage() {
  const { t } = useTranslation();
  const [tools, setToolsList] = useState<ToolInfo[]>([]);
  const [capabilities, setCapabilities] = useState<CapabilityInfo[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [capabilityConfigs, setCapabilityConfigs] = useState<CapabilityPlaygroundConfigMap>({});
  const [activeKind, setActiveKind] = useState<"tool" | "capability">("tool");
  const [activeName, setActiveName] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const [pluginRes, knowledgeBaseList] = await Promise.all([
          fetch(apiUrl("/api/v1/plugins/list")),
          listKnowledgeBases(),
        ]);
        const data = await pluginRes.json();
        const visibleTools = (data.tools || []).filter(
          (tool: ToolInfo) => !FRONTEND_HIDDEN_TOOLS.has(tool.name),
        );
        const visibleCapabilities = (data.capabilities || []).map((cap: CapabilityInfo) => ({
          ...cap,
          tools_used: filterFrontendTools(cap.tools_used ?? []),
        }));

        setToolsList(visibleTools);
        setCapabilities(visibleCapabilities);
        setCapabilityConfigs(loadCapabilityPlaygroundConfigs());
        setKnowledgeBases(knowledgeBaseList);

        if (visibleTools.length) {
          setActiveKind("tool");
          setActiveName(visibleTools[0].name);
        } else if (visibleCapabilities.length) {
          setActiveKind("capability");
          setActiveName(visibleCapabilities[0].name);
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const capabilityCatalog = capabilities;

  const activeTool = tools.find((t) => t.name === activeName);
  const activeCapability = capabilityCatalog.find((c) => c.name === activeName);
  const activeCapabilityConfig = useMemo(
    () =>
      activeCapability
        ? resolveCapabilityPlaygroundConfig(
            capabilityConfigs,
            activeCapability.name,
            activeCapability.tools_used ?? [],
          )
        : null,
    [activeCapability, capabilityConfigs],
  );
  const activeDeepQuestionConfig = useMemo(
    () => normalizeDeepQuestionConfig((activeCapabilityConfig?.config as Record<string, unknown> | undefined)),
    [activeCapabilityConfig?.config],
  );
  const activeDeepResearchConfig = useMemo(
    () =>
      normalizeResearchConfig(
        activeCapabilityConfig?.config as Record<string, unknown> | undefined,
      ),
    [activeCapabilityConfig?.config],
  );
  const listItems = useMemo(
    () =>
      activeKind === "tool"
        ? tools.map((t) => ({ name: t.name, description: t.description }))
        : capabilityCatalog.map((c) => ({ name: c.name, description: c.description })),
    [activeKind, capabilityCatalog, tools],
  );

  const persistCapabilityConfig = (capabilityName: string, next: CapabilityPlaygroundConfig) => {
    setCapabilityConfigs((prev) =>
      saveCapabilityPlaygroundConfig(prev, capabilityName, next),
    );
  };

  const toggleCapabilityTool = (toolName: string) => {
    if (!activeCapability || !activeCapabilityConfig) return;
    const allowedTools = filterFrontendTools(activeCapability.tools_used ?? []);
    if (!allowedTools.includes(toolName)) return;

    const enabledSet = new Set(activeCapabilityConfig.enabledTools);
    if (enabledSet.has(toolName)) enabledSet.delete(toolName);
    else enabledSet.add(toolName);

    const defaultKb =
      knowledgeBases.find((kb) => kb.is_default)?.name ??
      knowledgeBases[0]?.name ??
      "";

    persistCapabilityConfig(activeCapability.name, {
      enabledTools: allowedTools.filter((name) => enabledSet.has(name)),
      knowledgeBase:
        activeCapabilityConfig.knowledgeBase || (enabledSet.has("rag") ? defaultKb : ""),
      config: activeCapabilityConfig.config,
    });
  };

  const setCapabilityKnowledgeBase = (knowledgeBase: string) => {
    if (!activeCapability || !activeCapabilityConfig) return;
    persistCapabilityConfig(activeCapability.name, {
      enabledTools: activeCapabilityConfig.enabledTools,
      knowledgeBase,
      config: activeCapabilityConfig.config,
    });
  };

  const setDeepQuestionConfig = (next: DeepQuestionFormConfig) => {
    if (!activeCapability || !activeCapabilityConfig) return;
    persistCapabilityConfig(activeCapability.name, {
      enabledTools: activeCapabilityConfig.enabledTools,
      knowledgeBase: activeCapabilityConfig.knowledgeBase,
      config: next as unknown as Record<string, unknown>,
    });
  };

  const setDeepResearchConfig = (next: DeepResearchFormConfig) => {
    if (!activeCapability || !activeCapabilityConfig) return;
    persistCapabilityConfig(activeCapability.name, {
      enabledTools: activeCapabilityConfig.enabledTools,
      knowledgeBase: activeCapabilityConfig.knowledgeBase,
      config: next as unknown as Record<string, unknown>,
    });
  };

  return (
    <div className="min-h-screen bg-[var(--background)]">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight text-[var(--foreground)]">{t("Playground")}</h1>
          <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
            {t("Explore the building blocks of DeepTutor: reusable tools and higher-level capabilities.")}
          </p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
          </div>
        ) : (
          <div className="space-y-5">
            {/* Tab bar */}
            <div className="inline-flex rounded-lg border border-[var(--border)] bg-[var(--muted)] p-0.5">
              <button
                onClick={() => { setActiveKind("tool"); if (tools.length) setActiveName(tools[0].name); }}
                className={`rounded-md px-3.5 py-1.5 text-[13px] font-medium transition-all ${activeKind === "tool" ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"}`}
              >
                {t("Tools")}
              </button>
              <button
                onClick={() => { setActiveKind("capability"); if (capabilityCatalog.length) setActiveName(capabilityCatalog[0].name); }}
                className={`rounded-md px-3.5 py-1.5 text-[13px] font-medium transition-all ${activeKind === "capability" ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"}`}
              >
                {t("Capabilities")}
              </button>
            </div>

            {/* Two-column layout */}
            <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
              {/* Left: Item list */}
              <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
                <div className="mb-3 flex items-center gap-1.5">
                  {activeKind === "tool" ? <Terminal className="h-3.5 w-3.5 text-[var(--muted-foreground)]" /> : <Sparkles className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />}
                  <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
                    {activeKind === "tool" ? t("Tools") : t("Capabilities")}
                  </h2>
                </div>
                <div className="space-y-1">
                  {listItems.map((item) => {
                    const Icon = activeKind === "tool" ? getToolIcon(item.name) : getCapIcon(item.name);
                    return (
                      <button
                        key={item.name}
                        onClick={() => setActiveName(item.name)}
                        className={`w-full rounded-lg border px-3 py-2.5 text-left transition-all ${
                          activeName === item.name
                            ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                            : "border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] hover:border-[var(--foreground)]/10 hover:bg-[var(--muted)]"
                        }`}
                      >
                        <div className="flex items-center gap-1.5">
                          <Icon size={13} strokeWidth={1.7} />
                          <span className="text-[13px] font-medium">
                            {activeKind === "tool" ? t(getToolLabel(item.name)) : t(getCapabilityLabel(item.name))}
                          </span>
                        </div>
                        <div className={`mt-0.5 line-clamp-2 text-[11px] leading-relaxed ${activeName === item.name ? "text-[var(--primary-foreground)]/70" : "text-[var(--muted-foreground)]"}`}>
                          {item.description}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </section>

              {/* Right: Detail panel */}
              <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
                {activeKind === "tool" && activeTool ? (() => {
                  const ToolIcon = getToolIcon(activeTool.name);
                  return (
                    <div className="space-y-6">
                      <div>
                        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
                          <ToolIcon size={13} strokeWidth={1.7} />
                          {t("Tool")}
                        </div>
                        <h2 className="mt-1 text-xl font-bold tracking-tight text-[var(--foreground)]">{t(getToolLabel(activeTool.name))}</h2>
                        <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-[var(--muted-foreground)]">
                          {activeTool.description}
                        </p>
                      </div>

                      <div className="border-t border-[var(--border)] pt-6">
                        <ToolExecutor tool={activeTool} knowledgeBases={knowledgeBases} />
                      </div>
                    </div>
                  );
                })() : activeCapability ? (() => {
                  const CapIcon = getCapIcon(activeCapability.name);
                  return (
                    <div className="space-y-6">
                      <div>
                        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
                          <CapIcon size={13} strokeWidth={1.7} />
                          {t("Capability")}
                        </div>
                        <h2 className="mt-1 text-xl font-bold tracking-tight text-[var(--foreground)]">{t(getCapabilityLabel(activeCapability.name))}</h2>
                        <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-[var(--muted-foreground)]">
                          {activeCapability.description}
                        </p>
                      </div>

                      <div>
                        <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--muted-foreground)]">{t("Enable Tools")}</h3>
                        {!!activeCapability.tools_used?.length ? (
                          <div className="mt-2.5 flex flex-wrap gap-1.5">
                            {activeCapability.tools_used.map((tool) => {
                              const TIcon = getToolIcon(tool);
                              const enabled = activeCapabilityConfig?.enabledTools.includes(tool) ?? true;
                              return (
                                <button
                                  key={`${activeCapability.name}-${tool}`}
                                  onClick={() => toggleCapabilityTool(tool)}
                                  className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                                    enabled
                                      ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--primary)]"
                                      : "border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                                  }`}
                                >
                                  <TIcon size={11} strokeWidth={1.7} />
                                  {t(getToolLabel(tool))}
                                </button>
                              );
                            })}
                          </div>
                        ) : (
                          <p className="mt-2 text-[12px] text-[var(--muted-foreground)]">
                            {t("This capability runs without optional tools.")}
                          </p>
                        )}
                      </div>

                      {activeCapabilityConfig?.enabledTools.includes("rag") && (
                        <div>
                          <h3 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--muted-foreground)]">{t("Knowledge Base")}</h3>
                          <div className="mt-2.5 max-w-sm">
                            <select
                              value={activeCapabilityConfig.knowledgeBase}
                              onChange={(e) => setCapabilityKnowledgeBase(e.target.value)}
                              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/40"
                            >
                              <option value="">{t("Select knowledge base...")}</option>
                              {knowledgeBases.map((kb) => (
                                <option key={kb.name} value={kb.name}>
                                  {kb.name}
                                  {kb.is_default ? ` (${t("default")})` : ""}
                                </option>
                              ))}
                            </select>
                          </div>
                        </div>
                      )}

                      <div className="border-t border-[var(--border)] pt-6">
                        <div className="mb-3">
                          <h3 className="text-[14px] font-semibold text-[var(--foreground)]">{t("Try this capability")}</h3>
                          <p className="mt-0.5 text-[12px] text-[var(--muted-foreground)]">{t("Run a focused conversation here without leaving the playground.")}</p>
                        </div>
                        {activeCapability.name === "deep_question" ? (
                          <DeepQuestionTester
                            key={activeCapability.name}
                            capability={activeCapability}
                            enabledTools={activeCapabilityConfig?.enabledTools ?? activeCapability.tools_used ?? []}
                            knowledgeBase={activeCapabilityConfig?.knowledgeBase ?? ""}
                            config={activeDeepQuestionConfig}
                            onConfigChange={setDeepQuestionConfig}
                          />
                        ) : activeCapability.name === "deep_research" ? (
                          <DeepResearchTester
                            key={activeCapability.name}
                            capability={activeCapability}
                            enabledTools={activeCapabilityConfig?.enabledTools ?? activeCapability.tools_used ?? []}
                            knowledgeBase={activeCapabilityConfig?.knowledgeBase ?? ""}
                            config={activeDeepResearchConfig}
                            onConfigChange={setDeepResearchConfig}
                          />
                        ) : (
                          <CapabilityTester
                            key={activeCapability.name}
                            capability={activeCapability}
                            enabledTools={activeCapabilityConfig?.enabledTools ?? activeCapability.tools_used ?? []}
                            knowledgeBase={activeCapabilityConfig?.knowledgeBase ?? ""}
                          />
                        )}
                      </div>
                    </div>
                  );
                })() : null}
              </section>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
