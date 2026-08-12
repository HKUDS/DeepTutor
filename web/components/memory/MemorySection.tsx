"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  Bot,
  BookOpen,
  Brain,
  ClipboardList,
  ExternalLink,
  GitCommit,
  Library,
  Loader2,
  MessageSquare,
  NotebookPen,
  Pencil,
  PenLine,
  RefreshCw,
  Save,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiFetch, apiUrl } from "@/lib/api";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  { ssr: false },
);

// ── Types ────────────────────────────────────────────────────────────

type Layer = "L2" | "L3";

type Surface =
  | "chat"
  | "notebook"
  | "quiz"
  | "kb"
  | "book"
  | "partner"
  | "cowriter";

const SURFACES: readonly Surface[] = [
  "chat",
  "notebook",
  "quiz",
  "kb",
  "book",
  "partner",
  "cowriter",
] as const;

type Tab = "L1" | "L2" | "L3";

interface Entity {
  id: string;
  label: string;
  ts: string;
  content: string;
  metadata: Record<string, unknown>;
  fingerprint: string;
}

interface SnapshotResponse {
  surface: Surface;
  entities: Entity[];
  last_refresh: string | null;
  pending_changes: ChangeEntryDTO[];
}

interface ChangeEntryDTO {
  ts: string;
  kind: "added" | "modified" | "removed";
  entity_id: string;
  label: string;
  prev_fingerprint: string | null;
  new_fingerprint: string | null;
}

interface ChangesResponse {
  surface: Surface;
  changes: ChangeEntryDTO[];
}

interface KbQueryDTO {
  id: string;
  ts: string;
  surface: Surface;
  kind: string;
  payload: Record<string, unknown>;
  session_id: string | null;
  turn_id: string | null;
}

interface KbQueriesResponse {
  surface: Surface;
  events: KbQueryDTO[];
}

interface DocOverview {
  layer: Layer;
  key: string;
  exists: boolean;
  updated_at: string | null;
  entry_count: number;
  backlog: number;
}

interface OverviewResponse {
  docs: DocOverview[];
  backups: string[];
}

interface StreamStage {
  stage: string;
  count?: number;
  delta?: string;
  ops?: unknown[];
  report?: { accepted: boolean; reason?: string; results?: unknown[] };
  message?: string;
  // Agentic-loop fields (tool_called / tool_observed / step_done / loop_summary)
  turn?: number;
  name?: string;
  args?: Record<string, unknown>;
  brief?: string;
  action?: string;
  turns_used?: number;
  tools_used?: Record<string, number>;
  ops_emitted?: number;
  summary?: string;
}

// ── Surface metadata + helpers ───────────────────────────────────────

interface SurfaceMeta {
  icon: LucideIcon;
  label: string;
}

const SURFACE_META: Record<Surface, SurfaceMeta> = {
  chat: { icon: MessageSquare, label: "Chat" },
  notebook: { icon: NotebookPen, label: "Notebook" },
  quiz: { icon: ClipboardList, label: "题库" },
  kb: { icon: BookOpen, label: "Knowledge base" },
  book: { icon: Library, label: "Book" },
  partner: { icon: Bot, label: "Partner" },
  cowriter: { icon: PenLine, label: "Co-writer" },
};

const L3_LABELS: Record<string, string> = {
  recent: "近期总结",
  profile: "用户画像",
  scope: "知识 Scope",
  preferences: "偏好",
};

// Entity refs in L2/L3 docs are written as `<surface>:<entity_id>`.
// The id portion is intentionally permissive (notebook record_id, doc_id,
// book_id, bot name, session_id, "session:question" composites, kb_name).
const ENTITY_REF_RE =
  /\b(chat|notebook|quiz|kb|book|partner|cowriter):[A-Za-z0-9_.\-:]+/g;

function entityAnchorId(ref: string): string {
  // Anchor IDs can't contain ':' cleanly across CSS selectors — flatten
  // it. We never round-trip from anchor back to ref, so the encoding
  // can be lossy.
  return `entity-${ref.replace(/:/g, "__")}`;
}

function parseEntityAnchor(anchor: string): {
  surface: Surface;
  ref: string;
} | null {
  if (!anchor.startsWith("entity-")) return null;
  const body = anchor.slice("entity-".length);
  const sep = body.indexOf("__");
  if (sep <= 0) return null;
  const surface = body.slice(0, sep);
  const rest = body.slice(sep + 2).replace(/__/g, ":");
  if (!(SURFACES as readonly string[]).includes(surface)) return null;
  return { surface: surface as Surface, ref: `${surface}:${rest}` };
}

function linkifyEntityRefs(content: string): string {
  return content.replace(
    ENTITY_REF_RE,
    (ref) => `[${ref}](#${entityAnchorId(ref)})`,
  );
}

function labelFor(doc: DocOverview): string {
  if (doc.layer === "L2")
    return SURFACE_META[doc.key as Surface]?.label ?? doc.key;
  return L3_LABELS[doc.key] ?? doc.key;
}

function formatTimestamp(value: string | null, fallback: string): string {
  if (!value) return fallback;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function shorten(s: string, n: number): string {
  const trimmed = (s || "").replace(/\s+/g, " ").trim();
  return trimmed.length > n ? trimmed.slice(0, n - 1) + "…" : trimmed;
}

function asString(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "number") return String(v);
  return "";
}

function entityDeepLinkUrl(surface: Surface, ent: Entity): string | null {
  const m = ent.metadata || {};
  switch (surface) {
    case "chat":
      return `/home/${encodeURIComponent(ent.id)}`;
    case "cowriter":
      return `/co-writer/${encodeURIComponent(ent.id)}`;
    case "notebook": {
      const nbId = asString(m.notebook_id);
      return nbId
        ? `/space/notebooks?notebook=${encodeURIComponent(nbId)}`
        : "/space/notebooks";
    }
    case "book":
      return `/book?book=${encodeURIComponent(ent.id)}`;
    case "partner": {
      // Partner entity.id is `partnerId:sessionKey`. Deep-link to the partner.
      const partnerId = asString(m.partner_id) || ent.id.split(":")[0];
      return partnerId
        ? `/partners/${encodeURIComponent(partnerId)}`
        : "/partners";
    }
    case "quiz": {
      // Quiz entity.id is `session:question`. Deep-link to the session.
      const sessionId = asString(m.session_id) || ent.id.split(":")[0];
      return sessionId
        ? `/?session=${encodeURIComponent(sessionId)}`
        : "/space/questions";
    }
    case "kb":
      return `/knowledge?kb=${encodeURIComponent(ent.id)}`;
  }
  return null;
}

// ── Main component ──────────────────────────────────────────────────

interface MemorySectionProps {
  forcedTab?: Tab; // when provided, hides the TabStrip and locks the active tab
  hideHeader?: boolean; // when true, skips the SpaceSectionHeader (parent page renders its own)
}

export default function MemorySection({
  forcedTab,
  hideHeader = false,
}: MemorySectionProps = {}) {
  const { t, i18n } = useTranslation();
  const [tab, setTab] = useState<Tab>(forcedTab ?? "L2");
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [selected, setSelected] = useState<{
    layer: Layer;
    key: string;
  } | null>(null);
  const [content, setContent] = useState("");
  const [editing, setEditing] = useState(false);
  const [editorValue, setEditorValue] = useState("");
  const [stream, setStream] = useState<StreamStage[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [l1Surface, setL1Surface] = useState<Surface>("notebook");
  const [l1FocusRef, setL1FocusRef] = useState<string | null>(null);
  const [dismissedBackup, setDismissedBackup] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setDismissedBackup(
      window.localStorage.getItem("dt:memory:banner-dismissed") || null,
    );
  }, []);

  const latestBackup = overview?.backups?.[overview.backups.length - 1] ?? null;
  const showArchivedBanner = !!latestBackup && latestBackup !== dismissedBackup;

  const dismissArchivedBanner = useCallback(() => {
    if (!latestBackup) return;
    if (typeof window !== "undefined") {
      window.localStorage.setItem("dt:memory:banner-dismissed", latestBackup);
    }
    setDismissedBackup(latestBackup);
  }, [latestBackup]);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(apiUrl("/api/v1/memory/overview"));
      const data = (await res.json()) as OverviewResponse;
      setOverview(data);
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Failed to load overview");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(id);
  }, [toast]);

  const loadDoc = useCallback(async (layer: Layer, key: string) => {
    setSelected({ layer, key });
    setEditing(false);
    setStream([]);
    try {
      const res = await apiFetch(apiUrl(`/api/v1/memory/doc/${layer}/${key}`));
      const data = await res.json();
      const md = String(data?.content || "");
      setContent(md);
      setEditorValue(md);
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Failed to load document");
    }
  }, []);

  const saveDoc = useCallback(async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await apiFetch(
        apiUrl(`/api/v1/memory/doc/${selected.layer}/${selected.key}`),
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: editorValue }),
        },
      );
      setContent(editorValue);
      setEditing(false);
      setToast(t("Saved"));
      void loadOverview();
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setBusy(false);
    }
  }, [editorValue, loadOverview, selected, t]);

  const runUpdate = useCallback(async () => {
    if (!selected) return;
    if (selected.layer === "L3" && selected.key === "preferences") {
      setToast(
        t("Preferences is written by the chat assistant, not consolidated."),
      );
      return;
    }
    setBusy(true);
    setStream([]);
    try {
      const res = await apiFetch(
        apiUrl(`/api/v1/memory/doc/${selected.layer}/${selected.key}/update`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ language: i18n.language || "en" }),
        },
      );
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (reader) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let nl = buffer.indexOf("\n\n");
        while (nl !== -1) {
          const chunk = buffer.slice(0, nl);
          buffer = buffer.slice(nl + 2);
          const line = chunk
            .split("\n")
            .find((l) => l.startsWith("data:"))
            ?.replace(/^data:\s?/, "");
          if (line) {
            try {
              const evt = JSON.parse(line) as StreamStage;
              setStream((prev) => [...prev, evt]);
            } catch {
              // ignore malformed chunk
            }
          }
          nl = buffer.indexOf("\n\n");
        }
      }
      void loadDoc(selected.layer, selected.key);
      void loadOverview();
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Update failed");
    } finally {
      setBusy(false);
    }
  }, [i18n.language, loadDoc, loadOverview, selected, t]);

  // Clicking a `<surface>:<entity_id>` ref inside an L2/L3 doc opens
  // the L1 tab focused on that entity.
  const handleEntityLinkClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const link = (e.target as HTMLElement | null)?.closest("a");
      if (!link) return;
      const href = link.getAttribute("href") || "";
      if (!href.startsWith("#entity-")) return;
      const parsed = parseEntityAnchor(href.slice(1));
      if (!parsed) return;
      setTab("L1");
      setL1Surface(parsed.surface);
      setL1FocusRef(parsed.ref);
    },
    [],
  );

  const l2Rows = useMemo(
    () => (overview?.docs || []).filter((d) => d.layer === "L2"),
    [overview],
  );
  const l3Rows = useMemo(
    () => (overview?.docs || []).filter((d) => d.layer === "L3"),
    [overview],
  );

  return (
    <div className="space-y-6">
      {!hideHeader && (
        <SpaceSectionHeader
          icon={Brain}
          title={t("Memory")}
          description={t(
            "L1 mirrors your workspace, L2 summarises per-surface content, L3 is cross-surface knowledge.",
          )}
          meta={
            toast ? (
              <span className="rounded-full border border-[var(--primary)]/30 bg-[var(--primary)]/10 px-2 py-0.5 text-[10.5px] font-medium text-[var(--primary)]">
                {toast}
              </span>
            ) : null
          }
        />
      )}

      {!forcedTab && showArchivedBanner && latestBackup && (
        <div className="relative flex items-start gap-2 rounded-xl border border-[var(--border)] bg-[var(--muted)] px-4 py-3 pr-10 text-[13px]">
          <Archive className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
          <div>
            <p className="font-medium text-[var(--foreground)]">
              {t("Your v1 memory was archived")}
            </p>
            <p className="mt-0.5 text-[var(--muted-foreground)]">
              {t(
                "Stored at memory/backup/{{name}}. v2 starts fresh — interact with DeepTutor and click Update on each doc to build memory.",
                { name: latestBackup },
              )}
            </p>
          </div>
          <button
            type="button"
            onClick={dismissArchivedBanner}
            aria-label={t("Dismiss")}
            className="absolute right-2 top-2 rounded-md p-1.5 text-[var(--muted-foreground)] transition hover:bg-[var(--background)] hover:text-[var(--foreground)]"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {!forcedTab && (
        <TabStrip
          tab={tab}
          onChange={setTab}
          l2Count={l2Rows.length}
          l3Count={l3Rows.length}
          t={t}
        />
      )}

      {tab === "L1" && (
        <L1View
          surface={l1Surface}
          onSurfaceChange={(s) => {
            setL1Surface(s);
            setL1FocusRef(null);
          }}
          focusRef={l1FocusRef}
          onClearFocus={() => setL1FocusRef(null)}
          onToast={setToast}
          t={t}
        />
      )}

      {tab !== "L1" && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px,1fr]">
          <div className="space-y-4">
            <DocList
              title={t(
                tab === "L2" ? "L2 · Per-surface" : "L3 · Cross-surface",
              )}
              rows={tab === "L2" ? l2Rows : l3Rows}
              selected={selected}
              onSelect={loadDoc}
            />
          </div>

          <div className="space-y-4">
            {loading ? (
              <div className="flex min-h-[300px] items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
              </div>
            ) : !selected || selected.layer !== tab ? (
              <div className="flex min-h-[300px] flex-col items-center justify-center rounded-xl border border-dashed border-[var(--border)] text-center">
                <Brain className="mb-3 h-5 w-5 text-[var(--muted-foreground)]" />
                <p className="text-[14px] text-[var(--foreground)]">
                  {t("Pick a document to view or update")}
                </p>
              </div>
            ) : (
              <DocPane
                selected={selected}
                content={content}
                editing={editing}
                editorValue={editorValue}
                busy={busy}
                onEditValue={setEditorValue}
                onEditToggle={() => {
                  setEditing((v) => !v);
                  setEditorValue(content);
                }}
                onSave={saveDoc}
                onUpdate={runUpdate}
                onEntityLinkClick={handleEntityLinkClick}
                t={t}
              />
            )}

            {stream.length > 0 && (
              <StreamPanel
                stages={stream}
                onDismiss={() => setStream([])}
                t={t}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── TabStrip ────────────────────────────────────────────────────────

interface TabStripProps {
  tab: Tab;
  onChange: (tab: Tab) => void;
  l2Count: number;
  l3Count: number;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function TabStrip({ tab, onChange, l2Count, l3Count, t }: TabStripProps) {
  const tabs: Array<{ key: Tab; label: string; count?: number; hint: string }> =
    [
      {
        key: "L1",
        label: t("L1 · Workspace"),
        hint: t(
          "Live snapshot of your workspace — one entry per real artifact.",
        ),
      },
      {
        key: "L2",
        label: t("L2 · Per-surface"),
        count: l2Count,
        hint: t("Per-surface summaries consolidated from L1 content."),
      },
      {
        key: "L3",
        label: t("L3 · Cross-surface"),
        count: l3Count,
        hint: t("Cross-surface knowledge consolidated from L2."),
      },
    ];
  return (
    <div className="border-b border-[var(--border)]">
      <div className="flex gap-1">
        {tabs.map(({ key, label, count, hint }) => {
          const active = tab === key;
          return (
            <button
              key={key}
              onClick={() => onChange(key)}
              title={hint}
              className={`relative px-4 py-2 text-[13px] font-medium transition-colors ${
                active
                  ? "text-[var(--foreground)]"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              {label}
              {typeof count === "number" && (
                <span className="ml-2 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-normal text-[var(--muted-foreground)]">
                  {count}
                </span>
              )}
              {active && (
                <span
                  aria-hidden
                  className="absolute -bottom-px left-0 right-0 h-[2px] bg-[var(--foreground)]"
                />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── L1View (snapshot + changes per surface) ─────────────────────────

type L1Mode = "snapshot" | "changes" | "queries";

export interface L1ViewProps {
  surface: Surface;
  onSurfaceChange: (s: Surface) => void;
  focusRef: string | null;
  onClearFocus: () => void;
  onToast: (msg: string) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
  // When true, the surface pill bar is hidden — the parent renders its own
  // surface picker (e.g. a left rail in the workbench layout).
  compact?: boolean;
}

export function L1View({
  surface,
  onSurfaceChange,
  focusRef,
  onClearFocus,
  onToast,
  t,
  compact = false,
}: L1ViewProps) {
  const [mode, setMode] = useState<L1Mode>("snapshot");
  const [snapshot, setSnapshot] = useState<SnapshotResponse | null>(null);
  const [changes, setChanges] = useState<ChangeEntryDTO[]>([]);
  const [kbQueries, setKbQueries] = useState<KbQueryDTO[]>([]);
  const [loadingSnapshot, setLoadingSnapshot] = useState(false);
  const [loadingChanges, setLoadingChanges] = useState(false);
  const [loadingQueries, setLoadingQueries] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Default mode when switching surfaces:
  //  - kb: prefer "snapshot" but kb-only "queries" mode is accessible.
  //  - others: snapshot.
  useEffect(() => {
    if (mode === "queries" && surface !== "kb") {
      setMode("snapshot");
    }
  }, [surface, mode]);

  const loadSnapshot = useCallback(async () => {
    setLoadingSnapshot(true);
    try {
      const res = await apiFetch(apiUrl(`/api/v1/memory/snapshot/${surface}`));
      const data = (await res.json()) as SnapshotResponse;
      setSnapshot(data);
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to load snapshot");
    } finally {
      setLoadingSnapshot(false);
    }
  }, [surface, onToast]);

  const loadChanges = useCallback(async () => {
    setLoadingChanges(true);
    try {
      const res = await apiFetch(
        apiUrl(`/api/v1/memory/snapshot/${surface}/changes`),
      );
      const data = (await res.json()) as ChangesResponse;
      setChanges(data.changes);
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to load changes");
    } finally {
      setLoadingChanges(false);
    }
  }, [surface, onToast]);

  const loadKbQueries = useCallback(async () => {
    if (surface !== "kb") return;
    setLoadingQueries(true);
    try {
      const res = await apiFetch(apiUrl("/api/v1/memory/trace/kb?limit=200"));
      const data = (await res.json()) as KbQueriesResponse;
      setKbQueries(data.events);
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Failed to load queries");
    } finally {
      setLoadingQueries(false);
    }
  }, [surface, onToast]);

  useEffect(() => {
    setSnapshot(null);
    setChanges([]);
    setKbQueries([]);
    void loadSnapshot();
    void loadChanges();
    if (surface === "kb") void loadKbQueries();
  }, [surface, loadSnapshot, loadChanges, loadKbQueries]);

  // Auto-refetch snapshot when the tab regains focus or becomes visible —
  // workspace can mutate while the user is in another tab (notebook write,
  // co-writer edit, etc.) so the snapshot must reflect that without a click.
  useEffect(() => {
    const refetch = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      void loadSnapshot();
    };
    window.addEventListener("focus", refetch);
    document.addEventListener("visibilitychange", refetch);
    return () => {
      window.removeEventListener("focus", refetch);
      document.removeEventListener("visibilitychange", refetch);
    };
  }, [loadSnapshot]);

  // Auto-scroll to focused entity when snapshot finishes loading.
  useEffect(() => {
    if (!focusRef || !containerRef.current) return;
    if (!snapshot) return;
    const el = containerRef.current.querySelector(
      `[data-entity-ref="${focusRef}"]`,
    ) as HTMLElement | null;
    if (el) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [focusRef, snapshot]);

  const pendingByEntity = useMemo(() => {
    const m = new Map<string, ChangeEntryDTO["kind"]>();
    for (const c of snapshot?.pending_changes ?? []) {
      m.set(c.entity_id, c.kind);
    }
    return m;
  }, [snapshot?.pending_changes]);
  const pendingCount = snapshot?.pending_changes?.length ?? 0;

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await apiFetch(
        apiUrl(`/api/v1/memory/snapshot/${surface}/refresh`),
        { method: "POST" },
      );
      const data = await res.json();
      const newChanges: ChangeEntryDTO[] = data?.changes || [];
      onToast(
        newChanges.length > 0
          ? t("Refreshed: {{n}} changes", { n: newChanges.length })
          : t("Refreshed: no changes"),
      );
      await loadSnapshot();
      await loadChanges();
    } catch (e) {
      onToast(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  }, [surface, loadSnapshot, loadChanges, onToast, t]);

  return (
    <div className="space-y-3" ref={containerRef}>
      {!compact && (
        <div className="flex flex-wrap items-center gap-2">
          {SURFACES.map((s) => {
            const meta = SURFACE_META[s];
            return (
              <SurfacePill
                key={s}
                active={surface === s}
                onClick={() => onSurfaceChange(s)}
                icon={meta.icon}
                label={meta.label}
              />
            );
          })}
          <div className="ml-auto flex items-center gap-2">
            {pendingCount > 0 && (
              <span
                className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-300"
                title={t(
                  "Workspace changed since last refresh. Click Refresh to commit these to the changes log.",
                )}
              >
                {t("{{n}} pending", { n: pendingCount })}
              </span>
            )}
            <button
              onClick={() => void onRefresh()}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-50"
              title={t("Re-scan workspace and record any changes")}
            >
              {refreshing ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
              {t("Refresh")}
            </button>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between gap-2">
        <ModeStrip mode={mode} setMode={setMode} surface={surface} t={t} />
        {compact && (
          <div className="flex items-center gap-2">
            {pendingCount > 0 && (
              <span
                className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-300"
                title={t(
                  "Workspace changed since last refresh. Click Refresh to commit these to the changes log.",
                )}
              >
                {t("{{n}} pending", { n: pendingCount })}
              </span>
            )}
            <button
              onClick={() => void onRefresh()}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-50"
              title={t("Re-scan workspace and record any changes")}
            >
              {refreshing ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
              {t("Refresh")}
            </button>
          </div>
        )}
      </div>

      {mode === "snapshot" && (
        <SnapshotList
          surface={surface}
          loading={loadingSnapshot}
          snapshot={snapshot}
          pendingByEntity={pendingByEntity}
          focusRef={focusRef}
          onClearFocus={onClearFocus}
          t={t}
        />
      )}

      {mode === "changes" && (
        <ChangesList
          loading={loadingChanges}
          changes={changes}
          pending={snapshot?.pending_changes ?? []}
          t={t}
        />
      )}

      {mode === "queries" && surface === "kb" && (
        <KbQueriesList loading={loadingQueries} queries={kbQueries} t={t} />
      )}
    </div>
  );
}

// ── SurfacePill ─────────────────────────────────────────────────────

interface SurfacePillProps {
  active: boolean;
  onClick: () => void;
  icon: LucideIcon;
  label: string;
}

function SurfacePill({ active, onClick, icon: Icon, label }: SurfacePillProps) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] transition-colors ${
        active
          ? "border-[var(--primary)]/40 bg-[var(--primary)]/10 text-[var(--primary)]"
          : "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)]"
      }`}
    >
      <Icon className="h-3 w-3" />
      <span>{label}</span>
    </button>
  );
}

// ── ModeStrip (snapshot / changes / [kb queries]) ───────────────────

interface ModeStripProps {
  mode: L1Mode;
  setMode: (m: L1Mode) => void;
  surface: Surface;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function ModeStrip({ mode, setMode, surface, t }: ModeStripProps) {
  const tabs: Array<{ key: L1Mode; label: string; hidden?: boolean }> = [
    { key: "snapshot", label: t("Snapshot") },
    { key: "changes", label: t("Changes") },
    { key: "queries", label: t("Queries"), hidden: surface !== "kb" },
  ];
  return (
    <div className="inline-flex items-center gap-0.5 rounded-md border border-[var(--border)] bg-[var(--card)] p-0.5 text-[12px]">
      {tabs
        .filter((x) => !x.hidden)
        .map(({ key, label }) => {
          const active = mode === key;
          return (
            <button
              key={key}
              onClick={() => setMode(key)}
              className={`rounded px-2.5 py-1 transition-colors ${
                active
                  ? "bg-[var(--muted)] text-[var(--foreground)]"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              {label}
            </button>
          );
        })}
    </div>
  );
}

// ── SnapshotList ─────────────────────────────────────────────────────

interface SnapshotListProps {
  surface: Surface;
  loading: boolean;
  snapshot: SnapshotResponse | null;
  pendingByEntity: Map<string, ChangeEntryDTO["kind"]>;
  focusRef: string | null;
  onClearFocus: () => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function SnapshotList({
  surface,
  loading,
  snapshot,
  pendingByEntity,
  focusRef,
  onClearFocus,
  t,
}: SnapshotListProps) {
  const entities = snapshot?.entities ?? [];
  return (
    <>
      <div className="flex items-baseline justify-between text-[11.5px] text-[var(--muted-foreground)]">
        <span>
          {t("{{n}} entities", { n: entities.length })}
          {snapshot?.last_refresh && (
            <>
              {" · "}
              {t("last refresh {{ts}}", {
                ts: formatTimestamp(snapshot.last_refresh, ""),
              })}
            </>
          )}
        </span>
        {focusRef && (
          <button
            onClick={onClearFocus}
            className="text-[var(--primary)] hover:underline"
          >
            {t("Clear focus")}
          </button>
        )}
      </div>
      {loading && entities.length === 0 ? (
        <div className="flex items-center justify-center rounded-xl border border-[var(--border)] py-12">
          <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : entities.length === 0 ? (
        <p className="rounded-xl border border-[var(--border)] px-4 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
          {t("Nothing in workspace yet.")}
        </p>
      ) : (
        <ol className="rounded-xl border border-[var(--border)]">
          {entities.map((ent, idx) => (
            <EntityRow
              key={`${ent.id}#${idx}`}
              surface={surface}
              ent={ent}
              focused={focusRef === `${surface}:${ent.id}`}
              pendingKind={pendingByEntity.get(ent.id) ?? null}
              t={t}
            />
          ))}
        </ol>
      )}
    </>
  );
}

// ── EntityRow ───────────────────────────────────────────────────────

interface EntityRowProps {
  surface: Surface;
  ent: Entity;
  focused: boolean;
  pendingKind: ChangeEntryDTO["kind"] | null;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function EntityRow({ surface, ent, focused, pendingKind, t }: EntityRowProps) {
  const url = entityDeepLinkUrl(surface, ent);
  const ref = `${surface}:${ent.id}`;
  const meta = SURFACE_META[surface];
  const Icon = meta.icon;
  const preview = shorten(ent.content, 220);

  const inner = (
    <>
      <span
        className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded ${
          focused
            ? "bg-[var(--primary)]/25 text-[var(--primary)]"
            : "bg-[var(--muted)] text-[var(--muted-foreground)]"
        }`}
      >
        <Icon className="h-3 w-3" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 text-[11px] text-[var(--muted-foreground)]">
          <span className="truncate text-[13px] font-medium text-[var(--foreground)]">
            {ent.label}
          </span>
          <span className="font-mono opacity-70">{ent.id}</span>
          {ent.ts && <span>{formatTimestamp(ent.ts, "")}</span>}
          {pendingKind && <PendingBadge kind={pendingKind} t={t} />}
        </div>
        {preview && (
          <p className="mt-1 line-clamp-2 text-[12px] text-[var(--muted-foreground)]/90">
            {preview}
          </p>
        )}
      </div>
      {url && (
        <ExternalLink className="mt-1 h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)] group-hover:text-[var(--primary)]" />
      )}
    </>
  );

  const focusedRing = focused
    ? "border-l-[3px] border-l-[var(--primary)] bg-[var(--primary)]/12 ring-1 ring-[var(--primary)]/30"
    : pendingKind === "added"
      ? "border-l-[3px] border-l-emerald-500 bg-emerald-500/5 hover:bg-emerald-500/10"
      : pendingKind === "modified"
        ? "border-l-[3px] border-l-amber-500 bg-amber-500/5 hover:bg-amber-500/10"
        : "border-l-[3px] border-l-transparent hover:bg-[var(--muted)]/40";
  const rowClass = `group flex items-start gap-3 border-b border-[var(--border)]/50 px-4 py-2.5 transition-colors last:border-0 ${focusedRing}`;

  return (
    <li
      id={entityAnchorId(ref)}
      data-entity-ref={ref}
      title={t("Open in {{label}}", { label: meta.label })}
    >
      {url ? (
        <Link href={url} className={rowClass}>
          {inner}
        </Link>
      ) : (
        <div className={rowClass}>{inner}</div>
      )}
    </li>
  );
}

// ── PendingBadge (row-level pending marker) ─────────────────────────

function PendingBadge({
  kind,
  t,
}: {
  kind: ChangeEntryDTO["kind"];
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const map = {
    added: {
      label: t("new"),
      cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
    },
    modified: {
      label: t("modified"),
      cls: "border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300",
    },
    removed: {
      label: t("removed"),
      cls: "border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300",
    },
  } as const;
  const cfg = map[kind];
  return (
    <span
      className={`inline-flex items-center rounded-full border px-1.5 py-0 text-[10px] font-medium ${cfg.cls}`}
      title={t("Pending — not yet committed to changes log")}
    >
      {cfg.label}
    </span>
  );
}

// ── ChangesList (git-log style) ─────────────────────────────────────

interface ChangesListProps {
  loading: boolean;
  changes: ChangeEntryDTO[];
  pending: ChangeEntryDTO[];
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function ChangesList({ loading, changes, pending, t }: ChangesListProps) {
  if (loading && changes.length === 0 && pending.length === 0) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-[var(--border)] py-12">
        <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }
  const hasAny = changes.length > 0 || pending.length > 0;
  if (!hasAny) {
    return (
      <p className="rounded-xl border border-[var(--border)] px-4 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
        {t("No changes recorded yet. Run Refresh to capture the baseline.")}
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {pending.length > 0 && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/5">
          <div className="flex items-center justify-between border-b border-amber-500/30 px-4 py-1.5 text-[11px] font-medium text-amber-700 dark:text-amber-300">
            <span>
              {t("Pending — {{n}} change(s) since last refresh", {
                n: pending.length,
              })}
            </span>
            <span className="opacity-70">{t("Click Refresh to commit")}</span>
          </div>
          <ol>
            {pending.map((c, i) => (
              <ChangeRow key={`pending-${c.entity_id}-${i}`} c={c} />
            ))}
          </ol>
        </div>
      )}
      {changes.length > 0 && (
        <ol className="rounded-xl border border-[var(--border)]">
          {changes.map((c, i) => (
            <ChangeRow key={`${c.ts}-${c.entity_id}-${i}`} c={c} />
          ))}
        </ol>
      )}
    </div>
  );
}

function ChangeRow({ c }: { c: ChangeEntryDTO }) {
  return (
    <li className="flex items-start gap-3 border-b border-[var(--border)]/50 px-4 py-2 last:border-0">
      <ChangeGlyph kind={c.kind} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 text-[11px] text-[var(--muted-foreground)]">
          <span className="font-medium text-[var(--foreground)]">
            {c.label || c.entity_id}
          </span>
          <span className="font-mono opacity-70">{c.entity_id}</span>
          <span>{formatTimestamp(c.ts, "")}</span>
        </div>
      </div>
    </li>
  );
}

function ChangeGlyph({ kind }: { kind: ChangeEntryDTO["kind"] }) {
  const map = {
    added: { ch: "+", bg: "bg-emerald-500/15", fg: "text-emerald-600" },
    modified: { ch: "~", bg: "bg-amber-500/15", fg: "text-amber-600" },
    removed: { ch: "−", bg: "bg-rose-500/15", fg: "text-rose-600" },
  } as const;
  const cfg = map[kind];
  return (
    <span
      className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded font-mono text-[12px] font-bold ${cfg.bg} ${cfg.fg}`}
    >
      {cfg.ch}
    </span>
  );
}

// ── KbQueriesList (event-driven, only for KB) ───────────────────────

interface KbQueriesListProps {
  loading: boolean;
  queries: KbQueryDTO[];
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function KbQueriesList({ loading, queries, t }: KbQueriesListProps) {
  if (loading && queries.length === 0) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-[var(--border)] py-12">
        <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }
  if (queries.length === 0) {
    return (
      <p className="rounded-xl border border-[var(--border)] px-4 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
        {t("No RAG queries recorded yet.")}
      </p>
    );
  }
  return (
    <ol className="rounded-xl border border-[var(--border)]">
      {queries.map((q) => {
        const kb = asString(q.payload?.kb_name) || "?";
        const query = asString(q.payload?.query);
        return (
          <li
            key={q.id}
            className="flex items-start gap-3 border-b border-[var(--border)]/50 px-4 py-2 last:border-0"
          >
            <GitCommit className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2 text-[11px] text-[var(--muted-foreground)]">
                <span className="font-medium text-[var(--foreground)]">
                  {kb}
                </span>
                <span>{formatTimestamp(q.ts, "")}</span>
              </div>
              <p className="mt-0.5 truncate text-[12.5px] text-[var(--foreground)]">
                {query}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// ── DocList / DocPane / StreamPanel (mostly unchanged) ──────────────

interface DocListProps {
  title: string;
  rows: DocOverview[];
  selected: { layer: Layer; key: string } | null;
  onSelect: (layer: Layer, key: string) => void;
}

function DocList({ title, rows, selected, onSelect }: DocListProps) {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl border border-[var(--border)]">
      <div className="border-b border-[var(--border)] px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
        {title}
      </div>
      <ul>
        {rows.map((row) => {
          const isActive =
            selected?.layer === row.layer && selected.key === row.key;
          return (
            <li
              key={`${row.layer}-${row.key}`}
              className={`flex items-center justify-between border-b border-[var(--border)]/50 px-4 py-2 text-[13px] last:border-0 ${
                isActive ? "bg-[var(--muted)]" : "hover:bg-[var(--muted)]/50"
              }`}
            >
              <button
                onClick={() => onSelect(row.layer, row.key)}
                className="flex-1 text-left"
              >
                <span className="font-medium text-[var(--foreground)]">
                  {labelFor(row)}
                </span>
                <span className="ml-2 text-[11px] text-[var(--muted-foreground)]">
                  {row.entry_count} ·{" "}
                  {formatTimestamp(row.updated_at, t("not built"))}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

interface DocPaneProps {
  selected: { layer: Layer; key: string };
  content: string;
  editing: boolean;
  editorValue: string;
  busy: boolean;
  onEditValue: (v: string) => void;
  onEditToggle: () => void;
  onSave: () => void;
  onUpdate: () => void;
  onEntityLinkClick: (e: React.MouseEvent<HTMLDivElement>) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function DocPane({
  selected,
  content,
  editing,
  editorValue,
  busy,
  onEditValue,
  onEditToggle,
  onSave,
  onUpdate,
  onEntityLinkClick,
  t,
}: DocPaneProps) {
  const isPrefs = selected.layer === "L3" && selected.key === "preferences";
  const renderedContent = useMemo(() => linkifyEntityRefs(content), [content]);
  return (
    <div className="rounded-xl border border-[var(--border)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2">
        <span className="text-[14px] font-medium text-[var(--foreground)]">
          {selected.layer} ·{" "}
          {labelFor({
            layer: selected.layer,
            key: selected.key,
          } as DocOverview)}
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={onEditToggle}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1 text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            <Pencil className="h-3 w-3" />
            {editing ? t("Cancel") : t("Edit")}
          </button>
          {editing && (
            <button
              onClick={onSave}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--primary)]/40 bg-[var(--primary)]/10 px-2.5 py-1 text-[12px] font-medium text-[var(--primary)] disabled:opacity-50"
            >
              {busy ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Save className="h-3 w-3" />
              )}
              {t("Save")}
            </button>
          )}
          {!isPrefs && (
            <button
              onClick={onUpdate}
              disabled={busy || editing}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--primary)]/40 bg-[var(--primary)]/10 px-2.5 py-1 text-[12px] font-medium text-[var(--primary)] disabled:opacity-50"
            >
              {busy ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
              {t("Update")}
            </button>
          )}
        </div>
      </div>
      <div className="px-5 py-4">
        {editing ? (
          <textarea
            value={editorValue}
            onChange={(e) => onEditValue(e.target.value)}
            spellCheck={false}
            className="min-h-[420px] w-full resize-none rounded-lg border border-[var(--border)] bg-transparent p-3 font-mono text-[13px] leading-6 outline-none focus:border-[var(--ring)]"
          />
        ) : content.trim() ? (
          <div onClick={onEntityLinkClick}>
            <MarkdownRenderer
              content={renderedContent}
              variant="prose"
              className="text-[14px]"
            />
          </div>
        ) : (
          <p className="text-[13px] text-[var(--muted-foreground)]">
            {isPrefs
              ? t(
                  "Preferences are written when you explicitly tell the chat assistant your preferences (style, language, format).",
                )
              : t(
                  "Empty. Click Update to consolidate from the current snapshot.",
                )}
          </p>
        )}
      </div>
    </div>
  );
}

interface StreamPanelProps {
  stages: StreamStage[];
  onDismiss: () => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

function StreamPanel({ stages, onDismiss, t }: StreamPanelProps) {
  return (
    <div className="rounded-xl border border-[var(--border)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-2">
        <span className="text-[12px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Update progress")}
        </span>
        <button
          onClick={onDismiss}
          className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
        >
          <X className="h-3 w-3" />
        </button>
      </div>
      <ol className="space-y-2 px-4 py-3 text-[12px]">
        {stages.map((s, i) => (
          <li
            key={i}
            className="rounded bg-[var(--muted)]/50 px-3 py-2 font-mono"
          >
            <span className="font-semibold text-[var(--foreground)]">
              {s.stage}
              {typeof s.turn === "number" ? ` · t${s.turn}` : ""}
              {s.name ? ` · ${s.name}` : ""}
            </span>
            {typeof s.count === "number" && (
              <span className="ml-2 text-[var(--muted-foreground)]">
                count={s.count}
              </span>
            )}
            {s.delta && (
              <div className="mt-1 whitespace-pre-wrap text-[var(--muted-foreground)]">
                {s.delta}
              </div>
            )}
            {s.brief && (
              <div className="mt-1 text-[var(--muted-foreground)]">
                {s.brief}
              </div>
            )}
            {s.args && Object.keys(s.args).length > 0 && (
              <div className="mt-1 text-[var(--muted-foreground)]">
                args: {JSON.stringify(s.args)}
              </div>
            )}
            {s.ops && (
              <div className="mt-1 text-[var(--muted-foreground)]">
                ops: {s.ops.length}
              </div>
            )}
            {typeof s.ops_emitted === "number" && (
              <div className="mt-1 text-[var(--muted-foreground)]">
                ops_emitted={s.ops_emitted} · turns={s.turns_used ?? "?"}
                {s.tools_used
                  ? ` · ${Object.entries(s.tools_used)
                      .map(([k, v]) => `${k}=${v}`)
                      .join(", ")}`
                  : ""}
              </div>
            )}
            {s.report && (
              <div className="mt-1 text-[var(--muted-foreground)]">
                accepted={String(s.report.accepted)}
                {s.report.reason ? ` · ${s.report.reason}` : ""}
              </div>
            )}
            {s.message && (
              <div className="mt-1 text-[var(--muted-foreground)]">
                {s.message}
              </div>
            )}
            {s.summary && (
              <div className="mt-1 text-[var(--muted-foreground)]">
                {s.summary}
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
