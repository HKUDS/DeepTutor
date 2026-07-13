"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  Bot,
  ClipboardList,
  FileText,
  Hash,
  Layers,
  Library,
  Loader2,
  MessageSquare,
  Network,
  NotebookPen,
  PenLine,
  Pencil,
  Save,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { apiFetch, apiUrl } from "@/lib/api";
import MemoryRunPanel from "@/components/memory/MemoryRunPanel";

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  { ssr: false },
);

type Layer = "L2" | "L3";

// Each bullet ends with an HTML comment carrying the entry id
// (``<!--m_01HZK...-->``). The parser round-trips it but the rendered
// view should not show it as text — and we want clicking a same-doc
// m_xxx footnote to scroll the user back to the citing bullet. Convert
// the comment to an inline span with an ``id`` so:
//   * the rendered output is visually empty (zero-width span)
//   * ``#m_xxx`` hash navigation works within the doc
// Requires ``allowHtml`` on the markdown renderer (we set it below).
const _ENTRY_ANCHOR_RE = /\s*<!--\s*(m_[0-9A-HJKMNP-TV-Z]{26})\s*-->/g;

// Rewrite footnote definitions so the ref text becomes a markdown link.
//
// Four link targets, picked by (ref shape, current layer):
//   * ``surface:id``       → ``/memory/l1?ref=surface:id`` (L2 → L1 hop)
//   * ``m_<ULID>`` in L2   → ``#m_<ULID>`` (same-doc scroll; anchor
//     span above provides the target)
//   * ``m_<ULID>`` in L3   → ``/memory/resolve?id=m_<ULID>``
//     (legacy pre-pivot doc; resolver page redirects to the right L2)
//   * bare ``<surface>``   → ``/memory/l2/<surface>`` (L3 → L2 hop;
//     new design, L3 cites L2 files not L2 entries)
//
// The label regex is intentionally loose so this hits BOTH layouts —
// the new consolidated ``[^1]:`` and the legacy entry-keyed
// ``[^m_xxx]:`` — so docs that pre-date the merge step still get
// clickable footnotes until the next mode pass migrates them.
const _FOOTNOTE_DEF_LINKIFY_SURFACE_REF_RE =
  /^(\[\^[^\]]+\]:\s*)([a-z][a-z0-9_-]*):([A-Za-z0-9_-]+)\s*$/gm;
const _FOOTNOTE_DEF_LINKIFY_ENTRY_RE =
  /^(\[\^[^\]]+\]:\s*)(m_[0-9A-HJKMNP-TV-Z]{26})\s*$/gm;
// Bare surface name — keep tight (whitelist) so a typo can't accidentally
// turn into an L2 hub link.
const _L3_SURFACES = new Set([
  "chat",
  "notebook",
  "quiz",
  "kb",
  "book",
  "partner",
  "cowriter",
]);
const _FOOTNOTE_DEF_LINKIFY_BARE_RE =
  /^(\[\^[^\]]+\]:\s*)([a-z][a-z0-9_-]*)\s*$/gm;

function prepareDocForRender(md: string, layer: Layer): string {
  // Anchor injection MUST come before linkify so that ``m_xxx`` text on
  // a footnote-definition line is matched as a ref, not chewed up by the
  // anchor regex (which only matches inside HTML comments).
  const withAnchors = md.replace(
    _ENTRY_ANCHOR_RE,
    ' <span id="$1" class="memory-entry-anchor"></span>',
  );
  // ``surface:id`` must be tried before bare-surface because the bare
  // regex would otherwise match the surface prefix and leave ``:id``
  // dangling.
  const withSurfaceLinks = withAnchors.replace(
    _FOOTNOTE_DEF_LINKIFY_SURFACE_REF_RE,
    (_match, prefix: string, surface: string, entityId: string) => {
      const ref = `${surface}:${entityId}`;
      const url = `/memory/l1?ref=${encodeURIComponent(ref)}`;
      return `${prefix}[${ref}](${url})`;
    },
  );
  const withEntryLinks = withSurfaceLinks.replace(
    _FOOTNOTE_DEF_LINKIFY_ENTRY_RE,
    (_match, prefix: string, entryId: string) => {
      // L2: entry id refers to a bullet in *this* doc → local anchor.
      // L3: entry id refers to a bullet in some L2 doc → resolver page
      //     does the surface lookup, then redirects.
      const href =
        layer === "L2"
          ? `#${entryId}`
          : `/memory/resolve?id=${encodeURIComponent(entryId)}`;
      return `${prefix}[${entryId}](${href})`;
    },
  );
  // Bare surface name — only meaningful for L3 refs (new design).
  // Whitelist guards against linkifying arbitrary words that happen to
  // end up alone on a footnote definition line.
  return withEntryLinks.replace(
    _FOOTNOTE_DEF_LINKIFY_BARE_RE,
    (match, prefix: string, name: string) => {
      if (!_L3_SURFACES.has(name)) return match;
      return `${prefix}[${name}](/memory/l2/${name})`;
    },
  );
}

interface DocResponse {
  layer: Layer;
  key: string;
  content: string;
}

interface LineRowDTO {
  number: number;
  kind: "title" | "blank" | "section" | "bullet";
  text: string;
  entry_id: string | null;
  section: string | null;
}

interface DocOverview {
  layer: Layer;
  key: string;
  exists: boolean;
  updated_at: string | null;
  entry_count: number;
  backlog: number;
}

interface NavEntry {
  key: string;
  label: string;
  icon: LucideIcon;
}

const L2_NAV: NavEntry[] = [
  { key: "chat", icon: MessageSquare, label: "Chat" },
  { key: "notebook", icon: NotebookPen, label: "Notebook" },
  { key: "quiz", icon: ClipboardList, label: "Quiz" },
  { key: "kb", icon: BookOpen, label: "Knowledge base" },
  { key: "book", icon: Library, label: "Book" },
  { key: "partner", icon: Bot, label: "Partner" },
  { key: "cowriter", icon: PenLine, label: "Co-writer" },
];

const L3_NAV: NavEntry[] = [
  { key: "recent", icon: Network, label: "Recent summary" },
  { key: "profile", icon: Network, label: "User profile" },
  { key: "scope", icon: Network, label: "Knowledge scope" },
];

type ViewMode = "plain" | "lines";

export interface MemoryWorkbenchProps {
  layer: Layer;
  initialKey?: string;
  /**
   * Entry id to scroll into view + briefly highlight after the markdown
   * renders. Set by the deep-link contract (``?focus=m_xxx``) when the
   * user lands here from an L3 footnote click.
   */
  initialFocus?: string;
}

export default function MemoryWorkbench({
  layer,
  initialKey,
  initialFocus,
}: MemoryWorkbenchProps) {
  const { t } = useTranslation();
  const router = useRouter();
  const nav = layer === "L2" ? L2_NAV : L3_NAV;
  const [docKey, setDocKey] = useState<string>(initialKey || nav[0].key);

  useEffect(() => {
    if (initialKey) setDocKey(initialKey);
  }, [initialKey]);

  const [overview, setOverview] = useState<Record<string, DocOverview>>({});
  const [content, setContent] = useState("");
  const [lines, setLines] = useState<LineRowDTO[]>([]);
  const [view, setView] = useState<ViewMode>("plain");
  const [editing, setEditing] = useState(false);
  const [editorValue, setEditorValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");
  // Focus is one-shot — once we've scrolled-to + flashed the anchor we
  // don't want subsequent content reloads (e.g. after a Run) to keep
  // re-scrolling. ``initialFocus`` seeds it; the effect clears it.
  const [pendingFocus, setPendingFocus] = useState<string | null>(
    initialFocus || null,
  );
  const previewRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (initialFocus) setPendingFocus(initialFocus);
  }, [initialFocus]);

  const loadOverview = useCallback(async () => {
    const res = await apiFetch(apiUrl("/api/v1/memory/overview"));
    const data = await res.json();
    const map: Record<string, DocOverview> = {};
    for (const d of data.docs || []) {
      if (d.layer === layer) map[d.key] = d;
    }
    setOverview(map);
  }, [layer]);

  const loadDoc = useCallback(async () => {
    const res = await apiFetch(apiUrl(`/api/v1/memory/doc/${layer}/${docKey}`));
    const data = (await res.json()) as DocResponse;
    setContent(data?.content || "");
    setEditorValue(data?.content || "");
  }, [layer, docKey]);

  const loadLines = useCallback(async () => {
    const res = await apiFetch(
      apiUrl(`/api/v1/memory/doc/${layer}/${docKey}/lines`),
    );
    const data = (await res.json()) as { lines: LineRowDTO[] };
    setLines(data?.lines || []);
  }, [layer, docKey]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);
  useEffect(() => {
    void loadDoc();
    void loadLines();
  }, [loadDoc, loadLines]);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(""), 2200);
    return () => clearTimeout(id);
  }, [toast]);

  // Scroll-to + flash the focused entry once the markdown is in the
  // DOM. Markdown renders via a dynamic import → we can't fire on
  // ``content`` change alone; wait a frame so the anchor span exists.
  // ``editing`` mode hides the rendered preview, so skip then.
  useEffect(() => {
    if (!pendingFocus || editing) return;
    if (!content || !previewRef.current) return;
    const anchorId = pendingFocus.startsWith("m_")
      ? pendingFocus
      : `m_${pendingFocus}`;
    let cancelled = false;
    const id = window.setTimeout(() => {
      if (cancelled) return;
      const span = document.getElementById(anchorId);
      // Highlight the bullet, not the zero-width anchor span.
      const li = (span?.closest("li") as HTMLElement | null) ?? span;
      if (!li) return;
      li.scrollIntoView({ block: "center", behavior: "smooth" });
      const prev = {
        outline: li.style.outline,
        outlineOffset: li.style.outlineOffset,
        borderRadius: li.style.borderRadius,
        transition: li.style.transition,
      };
      li.style.outline = "2px solid var(--primary)";
      li.style.outlineOffset = "4px";
      li.style.borderRadius = "6px";
      li.style.transition = "outline-color 1.4s ease-out";
      const clear = window.setTimeout(() => {
        li.style.outline = prev.outline;
        li.style.outlineOffset = prev.outlineOffset;
        li.style.borderRadius = prev.borderRadius;
        li.style.transition = prev.transition;
      }, 1800);
      // Consume the focus token so reloads don't re-trigger.
      setPendingFocus(null);
      return () => window.clearTimeout(clear);
    }, 80);
    return () => {
      cancelled = true;
      window.clearTimeout(id);
    };
  }, [pendingFocus, content, editing]);

  const selectDoc = useCallback(
    (next: string) => {
      if (next === docKey) return;
      setDocKey(next);
      // Reflect selection in the URL so refresh + share keep state.
      router.replace(
        layer === "L2" ? `/memory/l2/${next}` : `/memory/l3/${next}`,
      );
    },
    [docKey, layer, router],
  );

  const saveDoc = useCallback(async () => {
    setSaving(true);
    try {
      await apiFetch(apiUrl(`/api/v1/memory/doc/${layer}/${docKey}`), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: editorValue }),
      });
      setContent(editorValue);
      setEditing(false);
      setToast(t("Saved"));
      void loadLines();
    } catch (e) {
      setToast(e instanceof Error ? e.message : t("Save failed"));
    } finally {
      setSaving(false);
    }
  }, [editorValue, layer, docKey, t, loadLines]);

  const nicelabel = useMemo(() => {
    const entry = nav.find((n) => n.key === docKey);
    return entry ? t(entry.label) : docKey;
  }, [docKey, nav, t]);

  const handleRunComplete = useCallback(() => {
    void loadDoc();
    void loadLines();
    void loadOverview();
  }, [loadDoc, loadLines, loadOverview]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 px-6 py-4 md:px-10">
      <div className="flex items-center justify-between gap-3">
        <Breadcrumb layer={layer} label={nicelabel} t={t} />
        <LayerSwitcher current={layer} t={t} />
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[180px_minmax(0,1fr)_360px] gap-4">
        {/* ── Left rail ── */}
        <aside className="min-h-0 overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] p-2">
          <ul className="space-y-0.5">
            {nav.map(({ key, icon: Icon, label }) => {
              const doc = overview[key];
              const active = key === docKey;
              return (
                <li key={key}>
                  <button
                    type="button"
                    onClick={() => selectDoc(key)}
                    className={
                      "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-[12.5px] text-left transition " +
                      (active
                        ? "bg-[var(--muted)] text-[var(--foreground)]"
                        : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]")
                    }
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    <span className="flex-1 truncate">{t(label)}</span>
                    {doc?.exists && (
                      <span className="rounded-full bg-[var(--background)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                        {doc.entry_count}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>

        {/* ── Center: preview ── */}
        <section className="flex min-h-0 flex-col gap-3">
          <div className="flex items-center justify-between gap-2">
            <ViewSwitch view={view} setView={setView} t={t} />
            {!editing ? (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[12px] transition hover:bg-[var(--muted)]"
              >
                <Pencil className="h-3.5 w-3.5" />
                {t("Edit raw")}
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setEditorValue(content);
                    setEditing(false);
                  }}
                  className="rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-[12px]"
                >
                  {t("Cancel")}
                </button>
                <button
                  type="button"
                  onClick={() => void saveDoc()}
                  disabled={saving}
                  className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-1 text-[12px] text-[var(--primary-foreground)] disabled:opacity-50"
                >
                  {saving ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  {t("Save")}
                </button>
              </div>
            )}
          </div>
          <div
            ref={previewRef}
            className="min-h-0 flex-1 overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5"
          >
            {editing ? (
              <textarea
                value={editorValue}
                onChange={(e) => setEditorValue(e.target.value)}
                className="h-[60vh] w-full resize-none rounded-md border border-[var(--border)] bg-[var(--background)] p-3 font-mono text-[12.5px] outline-none focus:border-[var(--primary)]"
              />
            ) : view === "lines" ? (
              <LineNumberedView lines={lines} t={t} />
            ) : content.trim().length > 0 ? (
              // The wrapper hides the default footnote backref arrow
              // (``data-footnote-backref``). Without this the rendered
              // doc has two clickable elements per footnote: the L1
              // text link we inject (correct) and the ↩ icon
              // remark-gfm auto-generates that jumps back to the
              // citation marker (confusing — users expect every link
              // in the footnote to go to L1).
              <div className="memory-doc-content [&_.data-footnote-backref]:hidden">
                <MarkdownRenderer
                  content={prepareDocForRender(content, layer)}
                  variant="prose"
                  className="text-[14px]"
                  allowHtml
                />
              </div>
            ) : (
              <EmptyState t={t} />
            )}
          </div>
          {toast && (
            <div className="self-start rounded-md border border-[var(--primary)]/30 bg-[var(--primary)]/10 px-3 py-1 text-[11.5px] text-[var(--primary)]">
              {toast}
            </div>
          )}
        </section>

        {/* ── Right: LLM work area ── */}
        <aside className="min-h-0">
          <MemoryRunPanel
            layer={layer}
            docKey={docKey}
            onRunComplete={handleRunComplete}
            onDocUpdated={handleRunComplete}
          />
        </aside>
      </div>
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────

function Breadcrumb({
  layer,
  label,
  t,
}: {
  layer: Layer;
  label: string;
  t: (k: string) => string;
}) {
  return (
    <div className="flex items-center gap-2 text-[12.5px]">
      <Link
        href="/memory"
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("Memory")}
      </Link>
      <span className="text-[var(--muted-foreground)]">/</span>
      <span className="inline-flex items-center gap-1.5 text-[var(--foreground)]">
        {layer === "L2" ? (
          <Workflow className="h-3.5 w-3.5" />
        ) : (
          <Network className="h-3.5 w-3.5" />
        )}
        {layer === "L2"
          ? t("L2 · Per-surface summaries")
          : t("L3 · Cross-surface knowledge")}
      </span>
      <span className="text-[var(--muted-foreground)]">/</span>
      <span className="text-[var(--foreground)]">{label}</span>
    </div>
  );
}

function LayerSwitcher({
  current,
  t,
}: {
  current: Layer;
  t: (k: string) => string;
}) {
  // L1 page is a single workbench (no per-key route); L2/L3 hubs land
  // on /memory/l2 and /memory/l3 which list the surfaces / slots.
  const entries: {
    key: "L1" | Layer;
    href: string;
    icon: LucideIcon;
    label: string;
  }[] = [
    { key: "L1", href: "/memory/l1", icon: Layers, label: t("L1") },
    { key: "L2", href: "/memory/l2", icon: Workflow, label: t("L2") },
    { key: "L3", href: "/memory/l3", icon: Network, label: t("L3") },
  ];
  return (
    <nav className="flex items-center gap-0.5 rounded-full border border-[var(--border)] bg-[var(--card)] p-0.5">
      {entries.map(({ key, href, icon: Icon, label }) => {
        const active = key === current;
        if (active) {
          return (
            <span
              key={key}
              className="inline-flex items-center gap-1 rounded-full bg-[var(--muted)] px-2.5 py-0.5 text-[11.5px] font-medium text-[var(--foreground)]"
            >
              <Icon className="h-3 w-3" />
              {label}
            </span>
          );
        }
        return (
          <Link
            key={key}
            href={href}
            className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11.5px] text-[var(--muted-foreground)] transition hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
          >
            <Icon className="h-3 w-3" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function ViewSwitch({
  view,
  setView,
  t,
}: {
  view: ViewMode;
  setView: (v: ViewMode) => void;
  t: (k: string) => string;
}) {
  const items: { key: ViewMode; label: string; icon: LucideIcon }[] = [
    { key: "plain", label: t("Rendered"), icon: FileText },
    { key: "lines", label: t("Line numbers"), icon: Hash },
  ];
  return (
    <div className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--background)] p-1">
      {items.map(({ key, label, icon: Icon }) => (
        <button
          key={key}
          type="button"
          onClick={() => setView(key)}
          className={
            "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] transition " +
            (view === key
              ? "bg-[var(--muted)] text-[var(--foreground)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/60")
          }
        >
          <Icon className="h-3.5 w-3.5" />
          {label}
        </button>
      ))}
    </div>
  );
}

function LineNumberedView({
  lines,
  t,
}: {
  lines: LineRowDTO[];
  t: (k: string) => string;
}) {
  if (lines.length === 0) return <EmptyState t={t} />;
  const width = Math.max(2, String(lines[lines.length - 1].number).length);
  return (
    <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[12.5px] leading-relaxed text-[var(--foreground)]">
      {lines.map((line) => {
        const num = String(line.number).padStart(width, " ");
        const muted = line.kind === "blank" || line.kind === "title";
        return (
          <div
            key={line.number}
            className={
              muted
                ? "text-[var(--muted-foreground)]"
                : "text-[var(--foreground)]"
            }
          >
            <span className="select-none pr-3 text-[var(--muted-foreground)]">
              {num}:
            </span>
            {line.text || " "}
          </div>
        );
      })}
    </pre>
  );
}

function EmptyState({ t }: { t: (k: string) => string }) {
  return (
    <div className="grid h-[300px] place-items-center text-center text-[13px] text-[var(--muted-foreground)]">
      <div className="max-w-sm space-y-2">
        <Workflow className="mx-auto h-6 w-6 opacity-60" />
        <p>{t("Empty. Click Update to extract facts from your traces.")}</p>
      </div>
    </div>
  );
}
