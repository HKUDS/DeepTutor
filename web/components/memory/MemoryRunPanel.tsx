"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleSlash,
  GitBranch,
  Loader2,
  Octagon,
  PlayCircle,
  RotateCcw,
  ScanSearch,
  Send,
  Sparkles,
  Trash2,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  listLLMOptions,
  llmSelectionKey,
  sameLLMSelection,
  type LLMOption,
} from "@/lib/llm-options";
import type { LLMSelection } from "@/lib/unified-ws";
import { apiFetch, apiUrl } from "@/lib/api";
import {
  useMemoryRun,
  type RunEvent,
  type RunMode,
} from "@/components/memory/useMemoryRun";

interface MemoryRunPanelProps {
  layer: "L2" | "L3";
  docKey: string;
  onRunComplete?: () => void;
  onDocUpdated?: () => void;
}

interface MemorySettingsDTO {
  update: { l2_budget: number; l3_budget: number };
  audit: { l2_budget: number; l3_budget: number };
  dedup: { iterations: number; auto_after_update: boolean };
}

const MODE_META: { key: RunMode; icon: LucideIcon; tKey: string }[] = [
  { key: "update", icon: Sparkles, tKey: "Update memory" },
  { key: "audit", icon: ScanSearch, tKey: "Audit memory" },
  { key: "dedup", icon: GitBranch, tKey: "Dedup" },
];

export default function MemoryRunPanel({
  layer,
  docKey,
  onRunComplete,
  onDocUpdated,
}: MemoryRunPanelProps) {
  const { t, i18n } = useTranslation();
  const { run, events, status, error, isRunning, start, cancel, undo, clear } =
    useMemoryRun(layer, docKey);

  const [mode, setMode] = useState<RunMode>("update");
  // Per-mode overrides keep typed values stable while the user flips between
  // modes — each mode has its own input value, defaulting to the settings
  // value when no override exists. Avoids setState-in-effect entirely.
  const [overrides, setOverrides] = useState<Record<RunMode, number | null>>({
    update: null,
    audit: null,
    dedup: null,
  });
  const budgetOverride = mode === "dedup" ? null : overrides[mode];
  const iterationsOverride = mode === "dedup" ? overrides.dedup : null;
  const setBudgetOverride = useCallback(
    (v: number | null) => setOverrides((prev) => ({ ...prev, [mode]: v })),
    [mode],
  );
  const setIterationsOverride = useCallback(
    (v: number | null) => setOverrides((prev) => ({ ...prev, dedup: v })),
    [],
  );
  const [selection, setSelection] = useState<LLMSelection | null>(null);
  const [activeDefault, setActiveDefault] = useState<LLMSelection | null>(null);
  const [modelOptions, setModelOptions] = useState<LLMOption[]>([]);
  const [modelLoading, setModelLoading] = useState(true);
  const [modelError, setModelError] = useState(false);
  const [settings, setSettings] = useState<MemorySettingsDTO | null>(null);

  // Load LLM options + memory settings once.
  useEffect(() => {
    setModelLoading(true);
    void (async () => {
      try {
        const data = await listLLMOptions();
        setModelOptions(data.options);
        setActiveDefault(data.active);
        setModelError(false);
      } catch {
        setModelOptions([]);
        setModelError(true);
      } finally {
        setModelLoading(false);
      }
    })();
    void (async () => {
      const res = await apiFetch(apiUrl("/api/v1/memory/settings"));
      const data = (await res.json()) as MemorySettingsDTO;
      setSettings(data);
    })();
  }, []);

  const defaultBudget = useMemo(() => {
    if (!settings) return null;
    if (mode === "update") {
      return layer === "L2"
        ? settings.update.l2_budget
        : settings.update.l3_budget;
    }
    if (mode === "audit") {
      return layer === "L2"
        ? settings.audit.l2_budget
        : settings.audit.l3_budget;
    }
    return null;
  }, [settings, mode, layer]);
  const defaultIterations = settings?.dedup.iterations ?? null;
  const budget = budgetOverride ?? defaultBudget ?? ("" as const);
  const iterations = iterationsOverride ?? defaultIterations ?? ("" as const);

  const effectiveSelection = useMemo(
    () => selection ?? activeDefault ?? null,
    [selection, activeDefault],
  );
  const handleRun = useCallback(() => {
    if (isRunning) return;
    const llmSelection = effectiveSelection
      ? {
          profile_id: effectiveSelection.profile_id,
          model_id: effectiveSelection.model_id,
        }
      : null;
    if (mode === "dedup") {
      void start({
        mode,
        iterations: typeof iterations === "number" ? iterations : undefined,
        llmSelection,
        language: i18n.language || "en",
      });
    } else {
      void start({
        mode,
        budget: typeof budget === "number" ? budget : undefined,
        llmSelection,
        language: i18n.language || "en",
      });
    }
  }, [
    isRunning,
    mode,
    iterations,
    budget,
    effectiveSelection,
    i18n.language,
    start,
  ]);

  // Notify parent when a run finishes (success or otherwise) so the doc
  // preview can refresh.
  const lastCompleted = useRef<string | null>(null);
  useEffect(() => {
    if (!run || isRunning) return;
    if (
      run.status === "done" ||
      run.status === "cancelled" ||
      run.status === "error"
    ) {
      if (lastCompleted.current !== run.id) {
        lastCompleted.current = run.id;
        onRunComplete?.();
      }
    }
  }, [run, isRunning, onRunComplete]);

  const lastDocEvent = useRef<number | null>(null);
  useEffect(() => {
    if (!onDocUpdated) return;
    const latest = [...events]
      .reverse()
      .find(
        (ev) =>
          ev.payload.stage === "doc_updated" ||
          ev.payload.stage === "undo_applied",
      );
    if (!latest || lastDocEvent.current === latest.seq) return;
    lastDocEvent.current = latest.seq;
    onDocUpdated();
  }, [events, onDocUpdated]);

  const undoDepth = useMemo(() => {
    let depth = run?.undo_count ?? 0;
    for (const ev of events) {
      const value = ev.payload.undo_depth;
      if (
        (ev.payload.stage === "doc_updated" ||
          ev.payload.stage === "undo_applied") &&
        typeof value === "number"
      ) {
        depth = value;
      }
    }
    return depth;
  }, [events, run?.undo_count]);

  const handleUndo = useCallback(() => {
    if (isRunning || undoDepth <= 0) return;
    void undo();
  }, [isRunning, undo, undoDepth]);

  const handleReset = useCallback(async () => {
    if (isRunning) return;
    const ok =
      typeof window !== "undefined" &&
      window.confirm(
        t(
          "Reset will delete the current memory file AND its seen-id state. The next Update will re-ingest every L1 entity from scratch. Continue?",
        ),
      );
    if (!ok) return;
    try {
      const res = await apiFetch(
        apiUrl(
          `/api/v1/memory/doc/${layer}/${encodeURIComponent(docKey)}/reset`,
        ),
        { method: "POST" },
      );
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(
          detail || t("reset failed: {{status}}", { status: res.status }),
        );
      }
      // Clear local run trace + tell the parent workbench to re-fetch the
      // (now empty) doc, line view, and overview badge.
      clear();
      onDocUpdated?.();
    } catch (e) {
      if (typeof window !== "undefined") {
        window.alert(
          t("Reset failed: {{msg}}", {
            msg: e instanceof Error ? e.message : t("unknown error"),
          }),
        );
      }
    }
  }, [isRunning, t, layer, docKey, clear, onDocUpdated]);

  const turns = useMemo(() => groupByTurn(events), [events]);

  return (
    <div className="flex h-full min-h-0 flex-col rounded-2xl border border-[var(--border)] bg-[var(--card)]">
      {/* Header */}
      <header className="flex items-center justify-between gap-2 border-b border-[var(--border)] px-3 py-2">
        <div className="flex items-center gap-1.5 text-[12.5px] font-semibold text-[var(--foreground)]">
          <Bot className="h-3.5 w-3.5 text-[var(--muted-foreground)]" />
          {t("LLM workspace")}
        </div>
        <div className="flex items-center gap-1">
          {run && events.length > 0 && (
            <>
              <button
                type="button"
                onClick={handleUndo}
                disabled={isRunning || undoDepth <= 0}
                className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
                title={t("Undo last memory edit")}
              >
                <Undo2 className="h-3 w-3" />
                {undoDepth > 0 && <span>{undoDepth}</span>}
              </button>
              <button
                type="button"
                onClick={clear}
                disabled={isRunning}
                className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40"
                title={t("Clear trace")}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => void handleReset()}
            disabled={isRunning}
            className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-700 hover:bg-amber-500/20 hover:text-amber-800 disabled:opacity-40 dark:text-amber-300 dark:hover:text-amber-200"
            title={t("Reset memory (delete md + seen-id state)")}
          >
            <RotateCcw className="h-3 w-3" />
            <span>{t("Reset")}</span>
          </button>
        </div>
      </header>

      {/* Composer — two evenly-distributed rows pinned at the top */}
      <div className="space-y-2 border-b border-[var(--border)] bg-[var(--background)]/40 px-3 py-2.5">
        <div className="grid grid-cols-3 gap-1.5">
          {MODE_META.map(({ key, icon: Icon, tKey }) => (
            <button
              key={key}
              type="button"
              disabled={isRunning}
              onClick={() => setMode(key)}
              className={
                "inline-flex min-w-0 items-center justify-center gap-1 rounded-full border border-[var(--border)] px-2 py-1 text-[11.5px] transition disabled:opacity-50 " +
                (mode === key
                  ? "bg-[var(--muted)] text-[var(--foreground)]"
                  : "bg-[var(--background)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]")
              }
            >
              <Icon className="h-3 w-3 shrink-0" />
              <span className="truncate">{t(tKey)}</span>
            </button>
          ))}
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-1.5">
          {mode === "dedup" ? (
            <NumberInput
              value={iterations}
              setValue={(v) => setIterationsOverride(v === "" ? null : v)}
              label={t("Iter")}
              min={1}
              max={20}
              disabled={isRunning}
              fullWidth
            />
          ) : (
            <NumberInput
              value={budget}
              setValue={(v) => setBudgetOverride(v === "" ? null : v)}
              label={t("Budget")}
              min={1}
              max={200}
              disabled={isRunning}
              fullWidth
            />
          )}
          <ModelPill
            options={modelOptions}
            value={selection ?? activeDefault}
            loading={modelLoading}
            error={modelError}
            disabled={isRunning}
            onChange={(next) => setSelection(next)}
            t={t}
          />
          {isRunning ? (
            <button
              type="button"
              onClick={() => void cancel()}
              className="inline-flex h-7 w-9 items-center justify-center rounded-full bg-[var(--muted)] text-[var(--foreground)] transition hover:opacity-90"
              title={t("Cancel")}
            >
              <Octagon className="h-3.5 w-3.5" />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleRun}
              className="inline-flex h-7 w-9 items-center justify-center rounded-full bg-[var(--primary)] text-[var(--primary-foreground)] transition hover:opacity-90"
              title={t("Run")}
            >
              <Send className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Stream */}
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {events.length === 0 && status === "idle" ? (
          <EmptyTrace t={t} />
        ) : (
          <ol className="space-y-2">
            {turns.map((turn) => (
              <TurnCard key={`${turn.kind}-${turn.id}`} turn={turn} t={t} />
            ))}
            {isRunning && (
              <li className="flex items-center gap-2 rounded-md bg-[var(--muted)]/40 px-2.5 py-1.5 text-[11.5px] text-[var(--muted-foreground)]">
                <Loader2 className="h-3 w-3 animate-spin" />
                {t("Working…")}
              </li>
            )}
            {error && (
              <li className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/5 px-2.5 py-1.5 text-[11.5px] text-red-500">
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {error}
              </li>
            )}
          </ol>
        )}
      </div>
    </div>
  );
}

// ── Trace pieces ─────────────────────────────────────────────────────

type Turn =
  | { kind: "system"; id: string; ts: string; payload: RunEvent["payload"] }
  | {
      kind: "llm";
      id: string;
      ts: string;
      turn: number;
      chunkIndex: number | null;
      system_prompt: string;
      user_prompt: string;
      response: string;
      error: string | null;
      label: string | null;
    };

function groupByTurn(events: RunEvent[]): Turn[] {
  const out: Turn[] = [];
  const pending: Record<string, Turn & { kind: "llm" }> = {};
  for (const ev of events) {
    const p = ev.payload as Record<string, unknown>;
    const stage = String(p.stage || "");
    if (stage === "llm_io_start") {
      const turn = typeof p.turn === "number" ? p.turn : 0;
      const chunkIndex =
        typeof p.chunk_index === "number" ? (p.chunk_index as number) : null;
      const key = `${turn}:${chunkIndex}:${ev.seq}`;
      const card: Turn & { kind: "llm" } = {
        kind: "llm",
        id: key,
        ts: ev.ts,
        turn,
        chunkIndex,
        system_prompt: String(p.system_prompt || ""),
        user_prompt: String(p.user_prompt || ""),
        response: "",
        error: null,
        label: typeof p.label === "string" ? p.label : null,
      };
      pending[`${turn}:${chunkIndex}`] = card;
      out.push(card);
      continue;
    }
    if (stage === "llm_io_end") {
      const turn = typeof p.turn === "number" ? p.turn : 0;
      const chunkIndex =
        typeof p.chunk_index === "number" ? (p.chunk_index as number) : null;
      const card = pending[`${turn}:${chunkIndex}`];
      if (card) {
        card.response = String(p.response || "");
        card.error = typeof p.error === "string" ? p.error : null;
        delete pending[`${turn}:${chunkIndex}`];
      }
      continue;
    }
    if (stage === "llm_io_delta") {
      const turn = typeof p.turn === "number" ? p.turn : 0;
      const chunkIndex =
        typeof p.chunk_index === "number" ? (p.chunk_index as number) : null;
      const card = pending[`${turn}:${chunkIndex}`];
      if (card) {
        card.response += String(p.delta || "");
      }
      continue;
    }
    out.push({
      kind: "system",
      id: `sys-${ev.seq}`,
      ts: ev.ts,
      payload: ev.payload,
    });
  }
  return out;
}

function TurnCard({ turn, t }: { turn: Turn; t: (k: string) => string }) {
  if (turn.kind === "system") {
    return <SystemEventRow event={turn.payload} t={t} />;
  }
  return <LLMTurnCard turn={turn} t={t} />;
}

function SystemEventRow({
  event,
  t,
}: {
  event: RunEvent["payload"];
  t: (k: string) => string;
}) {
  const stage = String(event.stage || "");
  const display = systemEventDisplay(stage, event, t);
  if (!display) return null;
  return (
    <li
      className={
        "flex items-start gap-2 rounded-md px-2 py-1.5 text-[11.5px] " +
        (display.tone === "ok"
          ? "border border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300"
          : display.tone === "warn"
            ? "border border-amber-500/30 bg-amber-500/5 text-amber-700 dark:text-amber-300"
            : "bg-[var(--muted)]/40 text-[var(--muted-foreground)]")
      }
    >
      <display.icon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div className="min-w-0">
        <div className="font-mono text-[10.5px] uppercase tracking-wide">
          {display.title}
        </div>
        {display.detail && (
          <div className="mt-0.5 break-words leading-snug">
            {display.detail}
          </div>
        )}
      </div>
    </li>
  );
}

function systemEventDisplay(
  stage: string,
  event: RunEvent["payload"],
  t: (k: string) => string,
): {
  icon: LucideIcon;
  title: string;
  detail: string;
  tone: "ok" | "warn" | "muted";
} | null {
  const num = (k: string) =>
    typeof event[k] === "number" ? String(event[k]) : null;
  const str = (k: string) =>
    typeof event[k] === "string" ? String(event[k]) : null;
  switch (stage) {
    case "run_started":
      return {
        icon: PlayCircle,
        title: t("Run started"),
        detail: `${event.mode}`,
        tone: "muted",
      };
    case "trace_loaded": {
      const total = num("total") ?? num("total_l2_entries");
      const fresh = num("new") ?? num("new_l2_entries");
      const parts = [
        total ? `total=${total}` : null,
        fresh ? `new=${fresh}` : null,
      ].filter(Boolean);
      return {
        icon: PlayCircle,
        title: t("Traces loaded"),
        detail: parts.join(" · "),
        tone: "muted",
      };
    }
    case "chunked":
      return {
        icon: PlayCircle,
        title: t("Chunked"),
        detail: [
          num("chunks") ? `chunks=${num("chunks")}` : null,
          num("budget") ? `budget=${num("budget")}` : null,
          num("chars") ? `chars=${num("chars")}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
        tone: "muted",
      };
    case "progress": {
      const turn = num("turn");
      const total = num("total");
      return {
        icon: PlayCircle,
        title: t("Progress"),
        detail: turn && total ? `${turn}/${total}` : "",
        tone: "muted",
      };
    }
    case "facts_extracted":
      return {
        icon: CheckCircle2,
        title: t("Facts extracted"),
        detail: [
          num("kept") ? `kept=${num("kept")}` : null,
          num("added") ? `added=${num("added")}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
        tone: "ok",
      };
    case "refs_dropped":
      return {
        icon: CircleSlash,
        title: t("Ref dropped"),
        detail: `${str("reason") || "?"} :: ${str("text") || ""}`,
        tone: "warn",
      };
    case "op_applied":
      return {
        icon: CheckCircle2,
        title: t("Edit applied"),
        detail: [str("op"), str("detail")].filter(Boolean).join(" · "),
        tone: "ok",
      };
    case "op_rejected":
      return {
        icon: CircleSlash,
        title: t("Edit rejected"),
        detail: [str("op"), str("detail")].filter(Boolean).join(" · "),
        tone: "warn",
      };
    case "doc_updated":
      return {
        icon: CheckCircle2,
        title: t("Markdown updated"),
        detail: [
          str("action"),
          num("turn") ? `turn=${num("turn")}` : null,
          num("undo_depth") ? `undo=${num("undo_depth")}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
        tone: "ok",
      };
    case "undo_applied":
      return {
        icon: Undo2,
        title: t("Undo applied"),
        detail: [
          str("action"),
          num("undo_depth") ? `remaining=${num("undo_depth")}` : "remaining=0",
        ]
          .filter(Boolean)
          .join(" · "),
        tone: "warn",
      };
    case "done":
      return {
        icon: CheckCircle2,
        title: t("Done"),
        detail: [
          num("facts_added") ? `+${num("facts_added")} facts` : null,
          num("edits_applied") ? `+${num("edits_applied")} edits` : null,
          num("refs_dropped") ? `dropped=${num("refs_dropped")}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
        tone: "ok",
      };
    case "run_ended":
      return {
        icon: CheckCircle2,
        title: t("Run ended"),
        detail: str("status") || "",
        tone: "muted",
      };
    case "cancelled":
      return {
        icon: CircleSlash,
        title: t("Cancelled"),
        detail: "",
        tone: "warn",
      };
    case "error":
      return {
        icon: AlertCircle,
        title: t("Error"),
        detail: str("message") || "",
        tone: "warn",
      };
    default:
      return null;
  }
}

function LLMTurnCard({
  turn,
  t,
}: {
  turn: Extract<Turn, { kind: "llm" }>;
  t: (k: string) => string;
}) {
  const [systemOpen, setSystemOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const tag =
    turn.chunkIndex !== null
      ? `t${turn.turn} · chunk ${turn.chunkIndex + 1}`
      : `t${turn.turn}`;
  return (
    <li className="space-y-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-2">
      <div className="flex items-center gap-2 text-[10.5px] uppercase tracking-wide text-[var(--muted-foreground)]">
        <Bot className="h-3 w-3" />
        <span>{turn.label || "llm"}</span>
        <span>·</span>
        <span>{tag}</span>
      </div>

      <Disclosure
        open={systemOpen}
        setOpen={setSystemOpen}
        label={t("System prompt")}
        body={turn.system_prompt}
      />
      <Disclosure
        open={userOpen}
        setOpen={setUserOpen}
        label={t("User prompt")}
        body={turn.user_prompt}
      />

      <div className="text-[12px] text-[var(--foreground)]">
        {turn.response ? (
          <pre className="whitespace-pre-wrap break-words font-mono text-[11.5px] leading-relaxed">
            {turn.response}
          </pre>
        ) : turn.error ? (
          <div className="rounded border border-red-500/30 bg-red-500/5 px-2 py-1 text-[11px] text-red-500">
            {turn.error}
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-[11.5px] text-[var(--muted-foreground)]">
            <Loader2 className="h-3 w-3 animate-spin" />
            {t("Streaming…")}
          </div>
        )}
      </div>
    </li>
  );
}

function Disclosure({
  open,
  setOpen,
  label,
  body,
}: {
  open: boolean;
  setOpen: (v: boolean) => void;
  label: string;
  body: string;
}) {
  if (!body) return null;
  return (
    <div className="text-[11px] text-[var(--muted-foreground)]">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1 rounded px-1 py-0.5 hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        {label}
        <span className="opacity-60">·&nbsp;{body.length}</span>
      </button>
      {open && (
        <pre className="mt-1 max-h-60 overflow-y-auto whitespace-pre-wrap break-words rounded bg-[var(--muted)]/40 px-2 py-1.5 font-mono text-[10.5px] text-[var(--foreground)]">
          {body}
        </pre>
      )}
    </div>
  );
}

// ── Composer pieces ─────────────────────────────────────────────────

function NumberInput({
  value,
  setValue,
  label,
  min,
  max,
  disabled,
  fullWidth = false,
}: {
  value: number | "";
  setValue: (n: number | "") => void;
  label: string;
  min: number;
  max: number;
  disabled: boolean;
  fullWidth?: boolean;
}) {
  return (
    <label
      className={
        "flex items-center justify-between gap-1 rounded-full border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[11.5px] text-[var(--muted-foreground)] " +
        (fullWidth ? "w-full" : "")
      }
    >
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        disabled={disabled}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "") return setValue("");
          const n = parseInt(v, 10);
          if (!Number.isNaN(n)) setValue(Math.max(min, Math.min(max, n)));
        }}
        className="w-14 bg-transparent text-right text-[11.5px] text-[var(--foreground)] outline-none"
      />
    </label>
  );
}

interface ModelPillProps {
  options: LLMOption[];
  value: LLMSelection | null;
  loading: boolean;
  error: boolean;
  disabled: boolean;
  onChange: (next: LLMSelection | null) => void;
  t: (k: string) => string;
}

function ModelPill({
  options,
  value,
  loading,
  error,
  disabled,
  onChange,
  t,
}: ModelPillProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const selectedOption = useMemo(
    () => options.find((o) => sameLLMSelection(o, value)) ?? null,
    [options, value],
  );
  const label = loading
    ? t("Loading models")
    : error
      ? t("Models unavailable")
      : selectedOption?.model_name || t("Default model");
  const inactive = disabled || loading || error || options.length === 0;

  return (
    <div ref={rootRef} className="relative w-full min-w-0">
      <button
        type="button"
        disabled={inactive}
        onClick={() => setOpen(!open)}
        title={
          selectedOption
            ? `${selectedOption.profile_name} | ${selectedOption.provider}`
            : label
        }
        className={
          "flex w-full min-w-0 items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[11.5px] text-[var(--foreground)] transition hover:bg-[var(--muted)]/60 disabled:opacity-50 " +
          (open ? "border-[var(--primary)]/40" : "")
        }
      >
        <Bot className="h-3 w-3 shrink-0 text-[var(--muted-foreground)]" />
        <span className="flex-1 truncate text-left">{label}</span>
        <ChevronDown className="h-3 w-3 shrink-0 text-[var(--muted-foreground)]" />
      </button>

      {open && !inactive && (
        <div className="absolute right-0 top-full z-30 mt-1 max-h-72 w-[min(320px,calc(100vw-32px))] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--card)] p-1 shadow-lg">
          {options.map((opt) => {
            const active = sameLLMSelection(opt, value);
            return (
              <button
                key={llmSelectionKey(opt)}
                type="button"
                onClick={() => {
                  onChange({
                    profile_id: opt.profile_id,
                    model_id: opt.model_id,
                  });
                  setOpen(false);
                }}
                className={
                  "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[11.5px] transition hover:bg-[var(--muted)] " +
                  (active
                    ? "bg-[var(--muted)] text-[var(--foreground)]"
                    : "text-[var(--muted-foreground)]")
                }
              >
                <span className="flex min-w-0 flex-1 items-baseline gap-2">
                  <span className="truncate text-[var(--foreground)]">
                    {opt.model_name}
                  </span>
                  <span className="shrink-0 text-[10px] opacity-60">
                    {opt.provider}
                  </span>
                </span>
                {opt.is_active_default && (
                  <span className="shrink-0 rounded bg-[var(--primary)]/10 px-1 py-0.5 text-[9.5px] uppercase text-[var(--primary)]">
                    {t("default")}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function EmptyTrace({ t }: { t: (k: string) => string }) {
  return (
    <div className="grid h-full place-items-center text-center text-[12.5px] text-[var(--muted-foreground)]">
      <div className="max-w-xs space-y-1.5">
        <Bot className="mx-auto h-6 w-6 opacity-60" />
        <p>
          {t(
            "Pick a mode and click Run. The LLM trace — system prompt, user prompt, response — appears here, turn by turn.",
          )}
        </p>
      </div>
    </div>
  );
}
