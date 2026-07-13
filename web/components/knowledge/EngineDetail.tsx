"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  Boxes,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleSlash,
  Cloud,
  Copy,
  Database,
  ExternalLink,
  KeyRound,
  Loader2,
  Network,
  RefreshCw,
  Server,
  Settings2,
  ShieldCheck,
  Workflow,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import {
  getEngineModelOptions,
  getEnginePreflight,
  getGraphRagConfig,
  getLightRagConfig,
  getLlamaIndexConfig,
  getPageIndexConfig,
  setEngineActiveModel,
  updateGraphRagConfig,
  updateLightRagConfig,
  updateLlamaIndexConfig,
  updatePageIndexConfig,
  type EnginePreflight,
  type GraphRagConfig,
  type LightRagConfig,
  type LlamaIndexConfig,
  type ModelOptionsByKind,
  type PageIndexConfig,
  type RagProviderSummary,
} from "@/lib/knowledge-api";
import {
  kbDocCount,
  kbProvider,
  resolveKbStatus,
  type KnowledgeBase,
} from "@/lib/knowledge-helpers";

interface EngineDetailProps {
  provider: RagProviderSummary;
  kbs: KnowledgeBase[];
  onBack: () => void;
  onOpenKb: (name: string) => void;
  onSelectMode: (providerId: string, mode: string) => Promise<void> | void;
  /** Called after a config change so the parent can refresh provider state. */
  onChanged: () => void;
  onError: (message: string) => void;
}

const ENGINE_ICONS: Record<string, LucideIcon> = {
  llamaindex: Boxes,
  pageindex: Cloud,
  graphrag: Network,
  lightrag: Workflow,
  "lightrag-server": Server,
};

const INSTALL_HINTS: Record<string, string> = {
  graphrag: "pip install 'deeptutor[graphrag]'",
  lightrag: "pip install 'deeptutor[rag-lightrag]'",
};

// Mode one-liners, keyed by `${engineId}:${mode}`. English source strings double
// as i18n keys (zh translations live in locales/zh/app.json).
const MODE_DESCRIPTIONS: Record<string, string> = {
  "graphrag:local":
    "Entity-focused retrieval over the relevant local subgraph — fast and economical.",
  "graphrag:global":
    "Map-reduce over global community summaries — best for broad, thematic questions.",
  "graphrag:drift":
    "Local retrieval with dynamic follow-ups — balances precision and coverage.",
  "graphrag:basic": "Plain vector retrieval — the lightest option.",
  "lightrag:naive": "Plain vector retrieval, without the knowledge graph.",
  "lightrag:local": "Local context focused on the most relevant entities.",
  "lightrag:global": "Theme-level retrieval over global relationships.",
  "lightrag:hybrid":
    "Combines local and global retrieval — a solid general default.",
  "lightrag:mix": "Fuses knowledge-graph and vector retrieval.",
  "lightrag-server:naive":
    "Plain vector retrieval, without the knowledge graph.",
  "lightrag-server:local":
    "Local context focused on the most relevant entities.",
  "lightrag-server:global": "Theme-level retrieval over global relationships.",
  "lightrag-server:hybrid":
    "Combines local and global retrieval — a solid general default.",
  "lightrag-server:mix":
    "Fuses knowledge-graph and vector retrieval — the server's default.",
};

// Model kinds each engine needs (for the in-place pickers). "vision" isn't a
// catalog service — it rides on the active chat model — so LightRAG only lists
// llm + embedding and shows a vision note under the chat picker. LightRAG Server
// owns its own models on the remote instance, so it needs none here.
const ENGINE_MODEL_KINDS: Record<string, ("llm" | "embedding")[]> = {
  llamaindex: ["embedding"],
  pageindex: [],
  graphrag: ["llm", "embedding"],
  lightrag: ["llm", "embedding"],
  "lightrag-server": [],
};

const MODEL_KIND_LABEL: Record<string, string> = {
  llm: "Chat model",
  embedding: "Embedding model",
};

// Free-form GraphRAG/LightRAG answer styles. Any string is accepted server-side;
// these are the common presets.
const RESPONSE_TYPE_PRESETS = [
  "Multiple Paragraphs",
  "Single Paragraph",
  "Single Sentence",
  "List of 3-7 Points",
  "Multiple-Page Report",
];

// Prerequisites prose per engine (English source doubles as i18n key).
const ENGINE_PREREQUISITES: Record<string, string> = {
  llamaindex:
    "Local vector engine — works out of the box. Retrieval uses your active embedding model; install the optional BM25 package to enable hybrid retrieval.",
  pageindex:
    "Hosted engine: documents are uploaded to PageIndex's servers for processing. Requires an API key; PDF / Markdown only.",
  graphrag:
    "Local knowledge-graph retrieval. Needs the optional dependency installed; indexing is LLM-heavy. Requires an active chat model and embedding model.",
  lightrag:
    "Graph + vector retrieval with multimodal parsing. Needs the optional dependency installed; indexing is LLM-heavy. Requires active chat and embedding models; multimodal also needs a vision model.",
};

type EngineStatus = "ready" | "needs_key" | "unavailable";

function resolveStatus(provider: RagProviderSummary): EngineStatus {
  if (provider.requires_api_key && provider.configured === false)
    return "needs_key";
  if (provider.configured === false) return "unavailable";
  return "ready";
}

function StatusBadge({ status }: { status: EngineStatus }) {
  const { t } = useTranslation();
  if (status === "ready") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10.5px] font-medium text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">
        <Check className="h-3 w-3" />
        {t("Ready")}
      </span>
    );
  }
  if (status === "needs_key") {
    return (
      <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10.5px] font-medium text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
        {t("Needs key")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full bg-[var(--muted)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
      {t("Not installed")}
    </span>
  );
}

/** Section shell: small uppercase label + bordered card body. */
function Section({
  label,
  icon: Icon,
  children,
}: {
  label: string;
  icon: LucideIcon;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-7">
      <h2 className="mb-3 flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </h2>
      {children}
    </section>
  );
}

function CopyableCommand({ command }: { command: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-2">
      <code className="truncate font-mono text-[12px] text-[var(--foreground)]">
        {command}
      </code>
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard?.writeText(command);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        }}
        className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
      >
        {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
        {copied ? t("Copied") : t("Copy")}
      </button>
    </div>
  );
}

/** Number field used by the LlamaIndex tuning form. */
function NumberField({
  label,
  hint,
  value,
  min,
  max,
  onChange,
  disabled,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  onChange: (next: number) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[12px] font-medium text-[var(--foreground)]">
        {label}
      </span>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
      />
      {hint && (
        <span className="text-[11px] text-[var(--muted-foreground)]">
          {hint}
        </span>
      )}
    </label>
  );
}

/* ----------------------------- Mode selector ----------------------------- */

function ModeSelector({
  provider,
  onSelectMode,
}: {
  provider: RagProviderSummary;
  onSelectMode: (providerId: string, mode: string) => Promise<void> | void;
}) {
  const { t } = useTranslation();
  const modes = useMemo(() => provider.modes ?? [], [provider.modes]);
  const [selected, setSelected] = useState(
    provider.default_mode || modes[0] || "",
  );
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    setSelected(provider.default_mode || modes[0] || "");
  }, [provider.default_mode, modes]);

  const pick = async (mode: string) => {
    if (mode === selected) return;
    setSelected(mode);
    setPending(mode);
    try {
      await onSelectMode(provider.id, mode);
    } finally {
      setPending(null);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {modes.map((mode) => {
        const active = mode === selected;
        const desc = MODE_DESCRIPTIONS[`${provider.id}:${mode}`];
        return (
          <button
            key={mode}
            type="button"
            onClick={() => void pick(mode)}
            className={`flex flex-col gap-1 rounded-xl border p-3 text-left transition-colors ${
              active
                ? "border-[var(--primary)] bg-[var(--primary)]/5"
                : "border-[var(--border)] hover:border-[var(--ring)]"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[12.5px] font-medium text-[var(--foreground)]">
                {mode}
              </span>
              {pending === mode ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--muted-foreground)]" />
              ) : active ? (
                <Check className="h-3.5 w-3.5 text-[var(--primary)]" />
              ) : null}
            </div>
            {desc && (
              <span className="text-[11.5px] leading-snug text-[var(--muted-foreground)]">
                {t(desc)}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* -------------------------- LlamaIndex config form ------------------------ */

function LlamaIndexForm({
  onChanged,
  onError,
}: {
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation();
  const [loaded, setLoaded] = useState<LlamaIndexConfig | null>(null);
  const [form, setForm] = useState<LlamaIndexConfig | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getLlamaIndexConfig({ force: true })
      .then((cfg) => {
        if (cancelled) return;
        setLoaded(cfg);
        setForm(cfg);
      })
      .catch((err) =>
        onError(err instanceof Error ? err.message : String(err)),
      );
    return () => {
      cancelled = true;
    };
    // onError is stable enough; we only want this on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty = useMemo(
    () => !!form && !!loaded && JSON.stringify(form) !== JSON.stringify(loaded),
    [form, loaded],
  );

  if (!form) {
    return (
      <div className="flex items-center justify-center rounded-2xl border border-[var(--border)] py-10">
        <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  const set = (patch: Partial<LlamaIndexConfig>) =>
    setForm((prev) => (prev ? { ...prev, ...patch } : prev));

  const save = async () => {
    if (!form) return;
    setSaving(true);
    try {
      const next = await updateLlamaIndexConfig({
        retrieval_profile: form.retrieval_profile,
        top_k: form.top_k,
        vector_top_k_multiplier: form.vector_top_k_multiplier,
        bm25_top_k_multiplier: form.bm25_top_k_multiplier,
        chunk_size: form.chunk_size,
        chunk_overlap: form.chunk_overlap,
      });
      setLoaded(next);
      setForm(next);
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const isHybrid = form.retrieval_profile === "hybrid";
  const profiles: {
    id: LlamaIndexConfig["retrieval_profile"];
    desc: string;
  }[] = [
    {
      id: "hybrid",
      desc: "BM25 keyword + vector semantic retrieval, fused and re-ranked. More robust recall.",
    },
    {
      id: "vector",
      desc: "Vector semantic retrieval only. Faster, but leans entirely on embedding quality.",
    },
  ];

  return (
    <div className="space-y-6 rounded-2xl border border-[var(--border)] p-4">
      {/* Retrieval profile */}
      <div>
        <div className="mb-2 text-[12px] font-medium text-[var(--foreground)]">
          {t("Retrieval profile")}
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {profiles.map((p) => {
            const active = form.retrieval_profile === p.id;
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => set({ retrieval_profile: p.id })}
                className={`flex flex-col gap-1 rounded-xl border p-3 text-left transition-colors ${
                  active
                    ? "border-[var(--primary)] bg-[var(--primary)]/5"
                    : "border-[var(--border)] hover:border-[var(--ring)]"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[12.5px] font-medium text-[var(--foreground)]">
                    {p.id}
                  </span>
                  {active && (
                    <Check className="h-3.5 w-3.5 text-[var(--primary)]" />
                  )}
                </div>
                <span className="text-[11.5px] leading-snug text-[var(--muted-foreground)]">
                  {t(p.desc)}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Retrieval breadth */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <NumberField
          label={t("Results per query")}
          value={form.top_k}
          min={1}
          max={50}
          onChange={(v) => set({ top_k: v })}
        />
        <NumberField
          label={t("Vector candidate ×")}
          hint={isHybrid ? undefined : t("Used by hybrid only")}
          value={form.vector_top_k_multiplier}
          min={1}
          max={10}
          disabled={!isHybrid}
          onChange={(v) => set({ vector_top_k_multiplier: v })}
        />
        <NumberField
          label={t("Keyword candidate ×")}
          hint={isHybrid ? undefined : t("Used by hybrid only")}
          value={form.bm25_top_k_multiplier}
          min={1}
          max={10}
          disabled={!isHybrid}
          onChange={(v) => set({ bm25_top_k_multiplier: v })}
        />
      </div>

      {/* Chunking */}
      <div>
        <div className="mb-2 flex items-baseline justify-between gap-2">
          <span className="text-[12px] font-medium text-[var(--foreground)]">
            {t("Chunking")}
          </span>
          <span className="text-[11px] text-[var(--muted-foreground)]">
            {t("Applies on the next re-index")}
          </span>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <NumberField
            label={t("Chunk size")}
            value={form.chunk_size}
            min={64}
            max={8192}
            onChange={(v) => set({ chunk_size: v })}
          />
          <NumberField
            label={t("Chunk overlap")}
            value={form.chunk_overlap}
            min={0}
            max={Math.max(0, form.chunk_size - 1)}
            onChange={(v) => set({ chunk_overlap: v })}
          />
        </div>
      </div>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => void save()}
          disabled={!dirty || saving}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {t("Save changes")}
        </button>
      </div>
    </div>
  );
}

/* -------------------------- PageIndex config form ------------------------- */

const PAGEINDEX_DEFAULT_BASE_URL = "https://api.pageindex.ai";

function PageIndexForm({
  onChanged,
  onError,
}: {
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation();
  const [config, setConfig] = useState<PageIndexConfig | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getPageIndexConfig({ force: true })
      .then((cfg) => {
        if (cancelled) return;
        setConfig(cfg);
        setBaseUrl(cfg.api_base_url || "");
      })
      .catch((err) =>
        onError(err instanceof Error ? err.message : String(err)),
      );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const persist = async (payload: {
    api_key?: string;
    api_base_url?: string;
  }) => {
    setSaving(true);
    try {
      const next = await updatePageIndexConfig(payload);
      setConfig(next);
      setApiKey("");
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const keySet = config?.api_key_set ?? false;

  return (
    <div className="space-y-4 rounded-2xl border border-[var(--border)] p-4">
      <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
        {t(
          "PageIndex is a hosted, vectorless retrieval engine. Documents in a PageIndex knowledge base are uploaded to PageIndex's servers for processing. One key is shared by all your PageIndex knowledge bases.",
        )}
      </p>

      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("API key")}
        </label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          disabled={saving}
          placeholder={
            keySet
              ? t("•••••••• (configured — leave blank to keep)")
              : t("Enter your PageIndex API key")
          }
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
        />
        {keySet && (
          <button
            type="button"
            onClick={() => void persist({ api_key: "" })}
            disabled={saving}
            className="mt-1.5 text-[11px] font-medium text-red-600 transition-colors hover:text-red-700 disabled:opacity-40 dark:text-red-400"
          >
            {t("Remove stored key")}
          </button>
        )}
      </div>

      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("API base URL")}
        </label>
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          disabled={saving}
          placeholder={PAGEINDEX_DEFAULT_BASE_URL}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
        />
      </div>

      <div className="flex items-center justify-between gap-2">
        <a
          href="https://dash.pageindex.ai/api-keys"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-[11.5px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          {t("Get an API key")}
          <ExternalLink className="h-3 w-3" />
        </a>
        <button
          type="button"
          onClick={() =>
            void persist({
              api_base_url: baseUrl.trim() || undefined,
              ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
            })
          }
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {t("Save changes")}
        </button>
      </div>
    </div>
  );
}

/* --------------------------- Shared form controls ------------------------- */

function ResponseTypeSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  const { t } = useTranslation();
  const known = RESPONSE_TYPE_PRESETS.includes(value);
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[12px] font-medium text-[var(--foreground)]">
        {t("Response style")}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full cursor-pointer rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25"
      >
        {RESPONSE_TYPE_PRESETS.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
        {!known && <option value={value}>{value}</option>}
      </select>
    </label>
  );
}

function ToggleField({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex flex-col">
        <span className="text-[12px] font-medium text-[var(--foreground)]">
          {label}
        </span>
        {hint && (
          <span className="text-[11px] text-[var(--muted-foreground)]">
            {hint}
          </span>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
          checked ? "bg-[var(--primary)]" : "bg-[var(--border)]"
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            checked ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </button>
    </div>
  );
}

function SaveButton({
  dirty,
  saving,
  onSave,
}: {
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex justify-end">
      <button
        type="button"
        onClick={onSave}
        disabled={!dirty || saving}
        className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {t("Save changes")}
      </button>
    </div>
  );
}

/** Shared loader + dirty-tracking scaffold for the small engine config forms. */
function useEngineForm<T>(
  load: () => Promise<T>,
  onError: (m: string) => void,
) {
  const [loaded, setLoaded] = useState<T | null>(null);
  const [form, setForm] = useState<T | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    load()
      .then((cfg) => {
        if (cancelled) return;
        setLoaded(cfg);
        setForm(cfg);
      })
      .catch((err) =>
        onError(err instanceof Error ? err.message : String(err)),
      );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dirty = useMemo(
    () => !!form && !!loaded && JSON.stringify(form) !== JSON.stringify(loaded),
    [form, loaded],
  );
  const patch = (p: Partial<T>) =>
    setForm((prev) => (prev ? { ...prev, ...p } : prev));
  return { loaded, form, setLoaded, setForm, saving, setSaving, dirty, patch };
}

/* -------------------------- GraphRAG config form -------------------------- */

function GraphRagForm({
  onChanged,
  onError,
}: {
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation();
  const { form, setLoaded, setForm, saving, setSaving, dirty, patch } =
    useEngineForm<GraphRagConfig>(
      () => getGraphRagConfig({ force: true }),
      onError,
    );

  if (!form) return <FormSkeleton />;

  const save = async () => {
    setSaving(true);
    try {
      const next = await updateGraphRagConfig({
        response_type: form.response_type,
        community_level: form.community_level,
        dynamic_community_selection: form.dynamic_community_selection,
      });
      setLoaded(next);
      setForm(next);
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5 rounded-2xl border border-[var(--border)] p-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <ResponseTypeSelect
          value={form.response_type}
          onChange={(v) => patch({ response_type: v })}
        />
        <NumberField
          label={t("Community level")}
          hint={t("Graph traversal granularity (local / drift)")}
          value={form.community_level}
          min={0}
          max={5}
          onChange={(v) => patch({ community_level: v })}
        />
      </div>
      <ToggleField
        label={t("Dynamic community selection")}
        hint={t("Global mode only")}
        checked={form.dynamic_community_selection}
        onChange={(v) => patch({ dynamic_community_selection: v })}
      />
      <SaveButton dirty={dirty} saving={saving} onSave={() => void save()} />
    </div>
  );
}

/* -------------------------- LightRAG config form -------------------------- */

function LightRagForm({
  onChanged,
  onError,
}: {
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation();
  const { form, setLoaded, setForm, saving, setSaving, dirty, patch } =
    useEngineForm<LightRagConfig>(
      () => getLightRagConfig({ force: true }),
      onError,
    );

  if (!form) return <FormSkeleton />;

  const save = async () => {
    setSaving(true);
    try {
      const next = await updateLightRagConfig({
        top_k: form.top_k,
        response_type: form.response_type,
      });
      setLoaded(next);
      setForm(next);
      onChanged();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5 rounded-2xl border border-[var(--border)] p-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <NumberField
          label={t("Results per query")}
          value={form.top_k}
          min={1}
          max={200}
          onChange={(v) => patch({ top_k: v })}
        />
        <ResponseTypeSelect
          value={form.response_type}
          onChange={(v) => patch({ response_type: v })}
        />
      </div>
      <SaveButton dirty={dirty} saving={saving} onSave={() => void save()} />
    </div>
  );
}

function FormSkeleton() {
  return (
    <div className="flex items-center justify-center rounded-2xl border border-[var(--border)] py-10">
      <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
    </div>
  );
}

/* ------------------------------ Model pickers ----------------------------- */

function ModelsSection({
  providerId,
  onError,
}: {
  providerId: string;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation();
  const kinds = useMemo(
    () => ENGINE_MODEL_KINDS[providerId] ?? [],
    [providerId],
  );
  const [data, setData] = useState<ModelOptionsByKind | null>(null);
  const [failed, setFailed] = useState(false);
  const [busyKind, setBusyKind] = useState<string | null>(null);

  useEffect(() => {
    if (kinds.length === 0) return;
    let cancelled = false;
    getEngineModelOptions(kinds)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [kinds]);

  const select = useCallback(
    async (kind: string, profileId: string, modelId: string) => {
      setBusyKind(kind);
      try {
        const updated = await setEngineActiveModel(kind, profileId, modelId);
        setData((prev) => (prev ? { ...prev, [kind]: updated } : prev));
      } catch (err) {
        onError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusyKind(null);
      }
    },
    [onError],
  );

  if (kinds.length === 0) return null;

  return (
    <Section label={t("Models")} icon={Boxes}>
      {failed ? (
        <div className="flex items-center justify-between gap-3 rounded-2xl border border-[var(--border)] p-4">
          <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "This engine uses your active chat and embedding models. Manage them in the model catalog.",
            )}
          </p>
          <Link
            href="/settings"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--ring)]"
          >
            {t("Open catalog")}
            <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
      ) : !data ? (
        <FormSkeleton />
      ) : (
        <div className="space-y-4 rounded-2xl border border-[var(--border)] p-4">
          {kinds.map((kind) => {
            const entry = data[kind];
            const value = `${entry?.active.profile_id ?? ""}::${entry?.active.model_id ?? ""}`;
            const hasOptions = (entry?.options.length ?? 0) > 0;
            return (
              <div key={kind} className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-medium text-[var(--foreground)]">
                    {t(MODEL_KIND_LABEL[kind] ?? kind)}
                  </span>
                  {busyKind === kind && (
                    <Loader2 className="h-3 w-3 animate-spin text-[var(--muted-foreground)]" />
                  )}
                </div>
                {hasOptions ? (
                  <select
                    value={value}
                    disabled={busyKind === kind}
                    onChange={(e) => {
                      const [pid, mid] = e.target.value.split("::");
                      void select(kind, pid, mid);
                    }}
                    className="w-full cursor-pointer rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
                  >
                    {entry!.options.map((o) => (
                      <option
                        key={`${o.profile_id}::${o.model_id}`}
                        value={`${o.profile_id}::${o.model_id}`}
                      >
                        {o.label}
                        {o.detail ? ` · ${o.detail}` : ""}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Link
                    href="/settings"
                    className="inline-flex w-fit items-center gap-1.5 rounded-lg border border-dashed border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                  >
                    {t("No models configured — open catalog")}
                    <ExternalLink className="h-3 w-3" />
                  </Link>
                )}
                {kind === "llm" && providerId === "lightrag" && (
                  <span className="text-[11px] text-[var(--muted-foreground)]">
                    {t(
                      "Multimodal documents need a vision-capable chat model.",
                    )}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Section>
  );
}

/* ----------------------- Requirements & environment ----------------------- */

function CheckRow({
  ok,
  optional,
  label,
  detail,
}: {
  ok: boolean;
  optional: boolean;
  label: string;
  detail: string;
}) {
  const { t } = useTranslation();
  const Icon = ok ? CheckCircle2 : optional ? CircleSlash : XCircle;
  const tone = ok
    ? "text-emerald-600 dark:text-emerald-400"
    : optional
      ? "text-[var(--muted-foreground)]"
      : "text-red-600 dark:text-red-400";
  return (
    <li className="flex items-start gap-2">
      <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${tone}`} />
      <div className="min-w-0">
        <span className="text-[12px] text-[var(--foreground)]">{t(label)}</span>
        {optional && (
          <span className="ml-1.5 text-[10px] text-[var(--muted-foreground)]">
            ({t("optional")})
          </span>
        )}
        {detail && (
          <div className="text-[11px] leading-snug text-[var(--muted-foreground)]">
            {detail}
          </div>
        )}
      </div>
    </li>
  );
}

function EnvRequirements({
  providerId,
  installHint,
  defaultOpen,
  onError,
}: {
  providerId: string;
  installHint?: string;
  defaultOpen: boolean;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen);
  const [report, setReport] = useState<EnginePreflight | null>(null);
  const [checking, setChecking] = useState(false);
  const prereq = ENGINE_PREREQUISITES[providerId];

  const runCheck = async () => {
    setChecking(true);
    try {
      setReport(await getEnginePreflight(providerId));
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setChecking(false);
    }
  };

  return (
    <section className="mt-7">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between rounded-lg py-1 text-left"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          <ShieldCheck className="h-3.5 w-3.5" />
          {t("Requirements & environment")}
        </span>
        <ChevronDown
          className={`h-4 w-4 text-[var(--muted-foreground)] transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>
      {open && (
        <div className="mt-3 space-y-3 rounded-2xl border border-[var(--border)] p-4">
          {prereq && (
            <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
              {t(prereq)}
            </p>
          )}
          {installHint && <CopyableCommand command={installHint} />}
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={() => void runCheck()}
              disabled={checking}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--ring)] disabled:opacity-50"
            >
              {checking ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {t("Check environment")}
            </button>
            {report && (
              <span
                className={`inline-flex items-center gap-1 text-[11.5px] font-medium ${
                  report.ok
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-amber-600 dark:text-amber-400"
                }`}
              >
                {report.ok ? t("Ready to use") : t("Not ready")}
              </span>
            )}
          </div>
          {report && (
            <ul className="space-y-1.5 border-t border-[var(--border)] pt-3">
              {report.checks.map((c) => (
                <CheckRow
                  key={c.key}
                  ok={c.ok}
                  optional={c.optional}
                  label={c.label}
                  detail={c.detail}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

/* ------------------------------ Main component ---------------------------- */

export default function EngineDetail({
  provider,
  kbs,
  onBack,
  onOpenKb,
  onSelectMode,
  onChanged,
  onError,
}: EngineDetailProps) {
  const { t } = useTranslation();
  const status = resolveStatus(provider);
  const Icon = ENGINE_ICONS[provider.id] ?? Boxes;
  const installHint = INSTALL_HINTS[provider.id];
  const hasModes = (provider.modes?.length ?? 0) > 0;

  const engineKbs = useMemo(
    () => kbs.filter((kb) => kbProvider(kb) === provider.id),
    [kbs, provider.id],
  );

  return (
    <div className="flex-1 overflow-y-auto bg-[var(--background)]">
      <div className="mx-auto max-w-3xl px-6 py-8">
        <button
          type="button"
          onClick={onBack}
          className="mb-3 inline-flex items-center gap-1 text-[11.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {t("Knowledge Center")}
        </button>

        {/* Header */}
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-[var(--border)] text-[var(--foreground)]">
            <Icon className="h-5 w-5" strokeWidth={1.6} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="font-serif text-[20px] font-semibold tracking-tight text-[var(--foreground)]">
                {provider.name}
              </h1>
              <StatusBadge status={status} />
            </div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
              {provider.description}
            </p>
          </div>
        </div>

        {/* Requirements & environment — collapsible, unified across engines.
            Auto-opens when the engine isn't ready so the gap is obvious. */}
        <EnvRequirements
          providerId={provider.id}
          installHint={installHint}
          defaultOpen={status !== "ready"}
          onError={onError}
        />

        {/* Retrieval modes (graphrag / lightrag) */}
        {hasModes && (
          <Section label={t("Retrieval mode")} icon={Workflow}>
            <p className="-mt-1 mb-3 text-[11.5px] leading-snug text-[var(--muted-foreground)]">
              {t(
                "The default for new searches. A knowledge base can still override it per-KB.",
              )}
            </p>
            <ModeSelector provider={provider} onSelectMode={onSelectMode} />
          </Section>
        )}

        {/* LlamaIndex tuning */}
        {provider.id === "llamaindex" && (
          <Section label={t("Retrieval & chunking")} icon={Settings2}>
            <LlamaIndexForm onChanged={onChanged} onError={onError} />
          </Section>
        )}

        {/* GraphRAG query knobs */}
        {provider.id === "graphrag" && (
          <Section label={t("Retrieval parameters")} icon={Settings2}>
            <GraphRagForm onChanged={onChanged} onError={onError} />
          </Section>
        )}

        {/* LightRAG query knobs */}
        {provider.id === "lightrag" && (
          <Section label={t("Retrieval parameters")} icon={Settings2}>
            <LightRagForm onChanged={onChanged} onError={onError} />
          </Section>
        )}

        {/* PageIndex credentials */}
        {provider.id === "pageindex" && (
          <Section label={t("Credentials")} icon={KeyRound}>
            <PageIndexForm onChanged={onChanged} onError={onError} />
          </Section>
        )}

        {/* Models — in-place pickers for the kinds this engine needs */}
        <ModelsSection providerId={provider.id} onError={onError} />

        {/* Knowledge bases on this engine */}
        <Section
          label={`${t("Knowledge bases")} · ${engineKbs.length}`}
          icon={Database}
        >
          {engineKbs.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-[var(--border)] px-4 py-8 text-center text-[12px] text-[var(--muted-foreground)]">
              {t("No knowledge bases use this engine yet.")}
            </div>
          ) : (
            <div className="overflow-hidden rounded-2xl border border-[var(--border)]">
              {engineKbs.map((kb, i) => {
                const docs = kbDocCount(kb);
                const ready = resolveKbStatus(kb) === "ready";
                return (
                  <button
                    key={kb.name}
                    type="button"
                    onClick={() => onOpenKb(kb.name)}
                    className={`flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors hover:bg-[var(--muted)]/40 ${
                      i > 0 ? "border-t border-[var(--border)]" : ""
                    }`}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <span
                        className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${
                          ready
                            ? "bg-emerald-500"
                            : "bg-[var(--muted-foreground)]"
                        }`}
                      />
                      <span className="truncate text-[13px] font-medium text-[var(--foreground)]">
                        {kb.name}
                      </span>
                    </div>
                    {docs !== null && (
                      <span className="shrink-0 text-[11px] text-[var(--muted-foreground)]">
                        {docs} {t("docs")}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}
