"use client";

/**
 * ChatNotebookTab — the viewer's Notebook tab.
 *
 * A scratch notebook kept with the conversation: Markdown cells for notes and
 * code cells that run in the same sandbox the tutor's `exec` tool uses, with
 * text, LaTeX and images shown inline. The cells are stored as one Co-Writer
 * page (fenced blocks are code, prose is Markdown), so the tutor can read and
 * search what the learner wrote.
 *
 * The page is bound to the conversation — and, when the conversation is a
 * mastery sitting, to its knowledge point — through a stored page pointer.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent,
  type CSSProperties,
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import dynamic from "next/dynamic";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Check,
  FileText,
  GripVertical,
  ImagePlus,
  Loader2,
  MoreHorizontal,
  Play,
  RefreshCw,
  Shapes,
  SquareTerminal,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import RichMarkdownRenderer from "@/components/common/RichMarkdownRenderer";
import RichCodeBlock from "@/components/common/RichCodeBlock";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import { apiUrl } from "@/lib/api";
import { getSession } from "@/lib/session-api";
import { fetchMasteryMap } from "@/lib/learning-api";
import { createNote, getNote, saveNote, uploadNoteAsset } from "@/lib/notes-api";
import {
  CODE_LANGUAGE_OPTIONS,
  createCodeCell,
  createGeogebraCell,
  createMarkdownCell,
  defaultNotebookCells,
  moveNotebookCell,
  normalizeCellLanguage,
  parseNotebookMarkdown,
  serializeNotebookMarkdown,
  type NotebookCell,
} from "@/lib/notebook-cells";
import {
  runNotebookCell,
  type NotebookCellRun,
} from "@/lib/notebook-lab-api";
import {
  appendNotebookGraph,
  emptyNotebookGraph,
  splitNotebookGraph,
  type NotebookGraph,
  type NotebookTag,
} from "@/lib/notebook-graph";
import NotebookTagControl from "@/components/chat/home/NotebookTagControl";

// GeoGebra loads its applet from a CDN; it must stay client-only.
const Geogebra = dynamic(() => import("@/components/Geogebra"), { ssr: false });
const NotebookGraphView = dynamic(
  () => import("@/components/chat/home/NotebookGraphView"),
  { ssr: false },
);

interface ChatNotebookTabProps {
  sessionId?: string | null;
  /** Open a notebook page directly by id (from the Notes home). */
  docId?: string | null;
  /** Leave the notebook page (from the Notes home); absent in the viewer. */
  onExit?: () => void;
}

type CellRun =
  | { status: "running" }
  | { status: "done"; run: NotebookCellRun }
  | { status: "error"; message: string };

type SaveState = "idle" | "saving" | "saved" | "error";

const POINTER_PREFIX = "dt:chat-notebook:";
const AUTOSAVE_MS = 900;

/** The split cell: editor, a draggable divider, preview. Stacks when narrow. */
const SPLIT_CELL_CSS = `
.nb-split { display: grid; grid-template-columns: 1fr; }
.nb-split-divider { display: none; }
@media (min-width: 1024px) {
  .nb-split {
    grid-template-columns:
      calc(var(--nb-split, 0.5) * 100%)
      8px
      calc((1 - var(--nb-split, 0.5)) * 100%);
  }
  .nb-split-divider {
    display: block;
    cursor: col-resize;
    touch-action: none;
    background: color-mix(in srgb, var(--border) 70%, transparent);
  }
  .nb-split-divider:hover {
    background: color-mix(in srgb, var(--primary) 45%, var(--border));
  }
}
`;

function pointerKey(
  owner: string,
  sessionId: string | null,
  pointId: string,
): string {
  return `${POINTER_PREFIX}${encodeURIComponent(owner)}:${
    sessionId ? encodeURIComponent(sessionId) : "pending"
  }:${pointId || "none"}`;
}

interface StoredPointer {
  id: string;
  revision: number;
}

function readPointer(key: string): StoredPointer | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<StoredPointer>;
    if (typeof value.id !== "string") return null;
    return { id: value.id, revision: Number(value.revision) || 0 };
  } catch {
    return null;
  }
}

function writePointer(key: string, pointer: StoredPointer): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(pointer));
  } catch {
    // Storage may be unavailable; the page still saves, it just cannot resume.
  }
}

/**
 * Restore each cell's saved id, so the graph's links (which point at ids) still
 * find their cells after a reload. Parsing mints fresh ids every time; the ids
 * persisted in the `dt-graph` block are the ones the links were written for.
 */
function applySavedCellIds(
  cells: NotebookCell[],
  ids: string[],
): NotebookCell[] {
  if (ids.length !== cells.length) return cells;
  return cells.map((cell, index) => ({ ...cell, id: ids[index] }));
}

/** Restore learner-given names from the hidden metadata block. */
function applySavedCellNames(
  cells: NotebookCell[],
  names: Record<string, string>,
): NotebookCell[] {
  if (!Object.keys(names).length) return cells;
  return cells.map((cell) =>
    names[cell.id] ? { ...cell, name: names[cell.id] } : cell,
  );
}

/** Collect non-empty cell names for the hidden metadata block. */
function collectCellNames(cells: NotebookCell[]): Record<string, string> {
  const names: Record<string, string> = {};
  for (const cell of cells) {
    const name = cell.name?.trim();
    if (name) names[cell.id] = name;
  }
  return names;
}

function cellKindLabel(
  cell: NotebookCell,
  t: (key: string) => string,
): string {
  return cell.kind === "code"
    ? t("Code")
    : cell.kind === "geogebra"
      ? t("GeoGebra board")
      : t("Note");
}

export default function ChatNotebookTab({ sessionId = null, docId = null, onExit }: ChatNotebookTabProps) {
  const { t } = useTranslation();
  const auth = useAuthStatus();
  const owner =
    !auth.loading && auth.statusAvailable
      ? auth.enabled
        ? auth.userId
        : "local"
      : null;

  const [ready, setReady] = useState(false);
  const [title, setTitle] = useState("");
  const [editingTitle, setEditingTitle] = useState(false);
  const [pointName, setPointName] = useState("");
  const [cells, setCells] = useState<NotebookCell[]>(() =>
    defaultNotebookCells(),
  );
  const [draggingCellId, setDraggingCellId] = useState<string | null>(null);
  const [dragOverCellId, setDragOverCellId] = useState<string | null>(null);
  const [graph, setGraph] = useState<NotebookGraph>(() => emptyNotebookGraph());
  const [view, setView] = useState<"list" | "graph">("list");
  const [runs, setRuns] = useState<Record<string, CellRun>>({});
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [error, setError] = useState("");

  const docIdRef = useRef<string | null>(null);
  const revisionRef = useRef(0);
  const pointerKeyRef = useRef<string>("");
  const notebookKeyRef = useRef<string>("default");
  const lastSavedRef = useRef<string>("");
  const lastSavedTitleRef = useRef<string>("");
  const pointIdRef = useRef<string>("");
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Resolve the bound page and load its cells whenever the conversation (and
  // its knowledge point) changes.
  useEffect(() => {
    if (!owner) return;
    let cancelled = false;
    setReady(false);
    setError("");
    setRuns({});

    void (async () => {
      if (docId) {
        // Opened directly from the Notes home: load this exact page.
        try {
          const page = await getNote(docId);
          if (cancelled) return;
          docIdRef.current = page.id;
          revisionRef.current = page.revision;
          notebookKeyRef.current = page.id;
          pointIdRef.current = "";
          pointerKeyRef.current = "";
          const loadedTitle = page.title || "";
          const markdown = page.content ?? "";
          lastSavedRef.current = markdown;
          lastSavedTitleRef.current = loadedTitle;
          setTitle(loadedTitle);
          setPointName("");
          const split = splitNotebookGraph(markdown);
          setCells(
            applySavedCellNames(
              applySavedCellIds(
                parseNotebookMarkdown(split.body),
                split.cellIds,
              ),
              split.names,
            ),
          );
          setGraph(split.graph);
        } catch (err) {
          if (!cancelled) setError(String(err));
        } finally {
          if (!cancelled) setReady(true);
        }
        return;
      }

      let pointId = "";
      let pathId = "";
      if (sessionId) {
        try {
          const detail = await getSession(sessionId);
          const prefs = detail.preferences ?? {};
          pointId = (prefs.mastery_knowledge_point_id ?? "").trim();
          pathId = (prefs.mastery_path_id ?? "").trim();
        } catch {
          // A conversation without readable preferences still gets a notebook.
        }
      }
      if (cancelled) return;

      // Show the knowledge point's name, not its id, when the map resolves.
      if (pointId && pathId) {
        try {
          const map = await fetchMasteryMap(pathId);
          const resolved = map.map.modules
            .flatMap((module) => module.knowledge_points)
            .find((point) => point.id === pointId)?.name;
          if (!cancelled && resolved) setPointName(resolved);
        } catch {
          // The id stands in until the map can be read.
        }
      } else {
        setPointName("");
      }
      if (cancelled) return;

      pointIdRef.current = pointId;
      notebookKeyRef.current = sessionId || "default";
      // A mastery notebook belongs to the knowledge point, not to one
      // conversation, so study, review and outline share it. The home chat has
      // no point, so its notebook stays per conversation.
      const scope = pointId || pathId;
      const key = scope
        ? `${POINTER_PREFIX}${encodeURIComponent(owner)}:point:${encodeURIComponent(pathId)}:${encodeURIComponent(pointId)}`
        : pointerKey(owner, sessionId, "");
      pointerKeyRef.current = key;

      let pointer = readPointer(key);
      // Adopt a notebook saved under the older session-scoped key.
      const legacyKey = scope ? pointerKey(owner, sessionId, scope) : "";
      if (!pointer && legacyKey && legacyKey !== key) {
        const legacy = readPointer(legacyKey);
        if (legacy) {
          writePointer(key, legacy);
          pointer = legacy;
        }
      }
      if (pointer) {
        try {
          const page = await getNote(pointer.id);
          if (cancelled) return;
          docIdRef.current = page.id;
          revisionRef.current = page.revision;
          const loadedTitle = page.title || "";
          const markdown = page.content ?? "";
          lastSavedRef.current = markdown;
          lastSavedTitleRef.current = loadedTitle;
          setTitle(loadedTitle);
          const split = splitNotebookGraph(markdown);
          setCells(
            applySavedCellNames(
              applySavedCellIds(
                parseNotebookMarkdown(split.body),
                split.cellIds,
              ),
              split.names,
            ),
          );
          setGraph(split.graph);
          setReady(true);
          return;
        } catch {
          // The page is gone (deleted elsewhere): start a fresh one.
        }
      }
      if (cancelled) return;
      docIdRef.current = null;
      revisionRef.current = 0;
      lastSavedRef.current = "";
      lastSavedTitleRef.current = "";
      setTitle("");
      setCells(defaultNotebookCells());
      setGraph(emptyNotebookGraph());
      setReady(true);
    })();

    return () => {
      cancelled = true;
    };
  }, [owner, sessionId, docId]);

  const persist = useCallback(
    async (nextCells: NotebookCell[], nextGraph: NotebookGraph) => {
      const markdown = appendNotebookGraph(
        serializeNotebookMarkdown(nextCells),
        nextGraph,
        nextCells.map((cell) => cell.id),
        collectCellNames(nextCells),
      );
      if (
        markdown === lastSavedRef.current &&
        title === lastSavedTitleRef.current
      ) {
        return;
      }
      setSaveState("saving");
      const pageTitle = title || t("Code notebook");

      const write = async () => {
        if (docIdRef.current) {
          const page = await saveNote(docIdRef.current, {
            title: pageTitle,
            content: markdown,
            expected_revision: revisionRef.current,
          });
          revisionRef.current = page.revision;
        } else {
          const page = await createNote(pageTitle, null, markdown, "super_note");
          docIdRef.current = page.id;
          revisionRef.current = page.revision;
        }
      };

      const finish = () => {
        lastSavedRef.current = markdown;
        lastSavedTitleRef.current = pageTitle;
        if (pointerKeyRef.current) {
          writePointer(pointerKeyRef.current, {
            id: docIdRef.current as string,
            revision: revisionRef.current,
          });
        }
        setSaveState("saved");
        setError("");
      };

      try {
        await write();
        finish();
      } catch (err) {
        // A stale revision (the page changed elsewhere) is the usual failure:
        // take the server's current revision and try once more, without
        // touching what is on screen.
        try {
          if (docIdRef.current) {
            const latest = await getNote(docIdRef.current);
            revisionRef.current = latest.revision;
          }
          await write();
          finish();
        } catch (retryErr) {
          setSaveState("error");
          setError(String(retryErr instanceof Error ? retryErr.message : retryErr));
        }
      }
    },
    [t, title],
  );

  // Debounced autosave. Never fires before the page has loaded, so restoring a
  // page cannot immediately rewrite it.
  useEffect(() => {
    if (!ready || !owner) return;
    const markdown = appendNotebookGraph(
      serializeNotebookMarkdown(cells),
      graph,
      cells.map((cell) => cell.id),
      collectCellNames(cells),
    );
    if (
      markdown === lastSavedRef.current &&
      title === lastSavedTitleRef.current
    ) {
      return;
    }
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      void persist(cells, graph);
    }, AUTOSAVE_MS);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [cells, graph, ready, owner, persist, title]);

  // Upload an image for a graph link's label. Assets hang off the page, so the
  // page is created first when a brand-new notebook has not saved yet.
  const uploadImage = useCallback(
    async (file: File): Promise<string> => {
      if (!docIdRef.current) {
        const markdown = appendNotebookGraph(
          serializeNotebookMarkdown(cells),
          graph,
          cells.map((cell) => cell.id),
          collectCellNames(cells),
        );
        const page = await createNote(
          t("Code notebook"),
          null,
          markdown,
          "super_note",
        );
        docIdRef.current = page.id;
        revisionRef.current = page.revision;
        lastSavedRef.current = markdown;
        if (pointerKeyRef.current) {
          writePointer(pointerKeyRef.current, {
            id: page.id,
            revision: page.revision,
          });
        }
      }
      const { url } = await uploadNoteAsset(docIdRef.current, file);
      return url;
    },
    [cells, graph, t],
  );

  const updateCell = useCallback((id: string, patch: Partial<NotebookCell>) => {
    setCells((prev) =>
      prev.map((cell) => (cell.id === id ? { ...cell, ...patch } : cell)),
    );
  }, []);

  const updateTag = useCallback((id: string, tag: NotebookTag | null) => {
    setGraph((prev) => {
      const tags = { ...prev.tags };
      if (tag) tags[id] = tag;
      else delete tags[id];
      return { ...prev, tags };
    });
  }, []);

  const addCell = useCallback((kind: NotebookCell["kind"]) => {
    const created =
      kind === "code"
        ? createCodeCell()
        : kind === "geogebra"
          ? createGeogebraCell()
          : createMarkdownCell();
    setCells((prev) => [...prev, created]);
  }, []);

  const removeCell = useCallback((id: string) => {
    setCells((prev) => {
      const next = prev.filter((cell) => cell.id !== id);
      return next.length ? next : [createMarkdownCell()];
    });
  }, []);

  const moveCell = useCallback((id: string, delta: number) => {
    setCells((prev) => {
      const index = prev.findIndex((cell) => cell.id === id);
      const target = index + delta;
      if (index < 0 || target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }, []);

  const reorderCell = useCallback((fromId: string, toId: string) => {
    setCells((prev) => moveNotebookCell(prev, fromId, toId));
  }, []);

  const runCell = useCallback(async (cell: NotebookCell) => {
    const language = normalizeCellLanguage(cell.language);
    setRuns((prev) => ({ ...prev, [cell.id]: { status: "running" } }));
    try {
      const run = await runNotebookCell({
        code: cell.source,
        language,
        notebookId: notebookKeyRef.current,
      });
      setRuns((prev) => ({ ...prev, [cell.id]: { status: "done", run } }));
    } catch (err) {
      setRuns((prev) => ({
        ...prev,
        [cell.id]: {
          status: "error",
          message: String(err instanceof Error ? err.message : err),
        },
      }));
    }
  }, []);

  const runAll = useCallback(async () => {
    for (const cell of cells) {
      if (cell.kind === "code" && cell.source.trim()) {
        // Sequential on purpose: later cells can read files earlier ones wrote.
        await runCell(cell);
      }
    }
  }, [cells, runCell]);

  const hasCode = useMemo(
    () => cells.some((cell) => cell.kind === "code" && cell.source.trim()),
    [cells],
  );

  if (!owner) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-[var(--muted-foreground)]">
        {t("Sign in to keep a notebook with this conversation.")}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <style>{SPLIT_CELL_CSS}</style>
      <div className="flex shrink-0 items-center gap-2.5 border-b border-[color-mix(in_srgb,var(--border)_45%,transparent)] px-4 py-3">
        {onExit ? (
          <button
            type="button"
            onClick={onExit}
            aria-label={t("Back to Notes")}
            title={t("Back to Notes")}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_70%,transparent)] hover:text-[var(--foreground)]"
          >
            <ArrowLeft size={16} strokeWidth={1.9} />
          </button>
        ) : null}
        <div className="min-w-0 flex-1">
          {editingTitle ? (
            <input
              autoFocus
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              onBlur={() => setEditingTitle(false)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === "Escape") {
                  setEditingTitle(false);
                }
              }}
              placeholder={t("Code notebook")}
              className="block w-full truncate rounded-md border border-[var(--border)] bg-transparent px-1 text-[13.5px] font-semibold text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
            />
          ) : (
            <button
              type="button"
              onClick={() => setEditingTitle(true)}
              title={t("Rename")}
              className="block max-w-full truncate rounded-md text-left text-[13.5px] font-semibold text-[var(--foreground)] transition-colors hover:text-[var(--primary)]"
            >
              {title || t("Code notebook")}
            </button>
          )}
          <div className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
            {pointName || pointIdRef.current
              ? t("Bound to knowledge point {{id}}", {
                  id: pointName || pointIdRef.current,
                })
              : t("Notes and runnable code, kept with this conversation.")}
          </div>
        </div>
        <SaveBadge
          state={saveState}
          label={t}
          onRetry={() => void persist(cells, graph)}
        />
        <div className="flex shrink-0 items-center gap-0.5 rounded-xl border border-[color-mix(in_srgb,var(--border)_55%,transparent)] bg-[color-mix(in_srgb,var(--muted)_22%,transparent)] p-0.5">
          {(["list", "graph"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setView(mode)}
              aria-pressed={view === mode}
              className={`rounded-lg px-2.5 py-1 text-[11px] font-medium transition-colors ${
                view === mode
                  ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              {t(mode === "list" ? "List" : "Graph")}
            </button>
          ))}
        </div>
        {hasCode ? (
          <button
            type="button"
            onClick={() => void runAll()}
            className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-[color-mix(in_srgb,var(--border)_55%,transparent)] px-2.5 py-1.5 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_45%,transparent)] hover:text-[var(--foreground)]"
          >
            <Play size={11} strokeWidth={2} />
            {t("Run all")}
          </button>
        ) : null}
      </div>

      <div
        className={
          view === "graph"
            ? "min-h-0 flex-1 overflow-hidden"
            : "min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3.5 py-4"
        }
      >
        {!ready ? (
          <div className="flex items-center gap-2 p-3 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 size={13} className="animate-spin" />
            {t("Loading notebook…")}
          </div>
        ) : view === "graph" ? (
          <div className="h-full w-full">
            <NotebookGraphView
              cells={cells}
              graph={graph}
              onGraphChange={setGraph}
              onCellChange={updateCell}
              onUploadImage={uploadImage}
              onTagChange={updateTag}
              onAddCell={addCell}
            />
          </div>
        ) : (
          <>
            {cells.map((cell, index) => (
              <CellCard
                key={cell.id}
                cell={cell}
                index={index}
                total={cells.length}
                run={runs[cell.id]}
                tag={graph.tags[cell.id]}
                dragging={draggingCellId === cell.id}
                dragOver={
                  dragOverCellId === cell.id && draggingCellId !== cell.id
                }
                onDragStart={() => setDraggingCellId(cell.id)}
                onDragOver={() => setDragOverCellId(cell.id)}
                onDragEnd={() => {
                  setDraggingCellId(null);
                  setDragOverCellId(null);
                }}
                onDrop={() => {
                  if (draggingCellId) {
                    reorderCell(draggingCellId, cell.id);
                  }
                  setDraggingCellId(null);
                  setDragOverCellId(null);
                }}
                onUploadImage={uploadImage}
                onChange={(patch) => updateCell(cell.id, patch)}
                onTagChange={(next) => updateTag(cell.id, next)}
                onRun={() => void runCell(cell)}
                onMove={(delta) => moveCell(cell.id, delta)}
                onRemove={() => removeCell(cell.id)}
              />
            ))}

            <div className="flex flex-wrap gap-2 pt-1.5">
              {(
                [
                  { kind: "markdown", icon: FileText, label: "Note cell" },
                  { kind: "code", icon: SquareTerminal, label: "Code cell" },
                  { kind: "geogebra", icon: Shapes, label: "Board cell" },
                ] as const
              ).map(({ kind, icon: Icon, label }) => (
                <button
                  key={kind}
                  type="button"
                  onClick={() => addCell(kind)}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-dashed border-[color-mix(in_srgb,var(--border)_75%,transparent)] bg-[color-mix(in_srgb,var(--muted)_12%,transparent)] px-3 py-2 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[color-mix(in_srgb,var(--primary)_35%,var(--border))] hover:bg-[color-mix(in_srgb,var(--muted)_35%,transparent)] hover:text-[var(--foreground)]"
                >
                  <Icon size={13} strokeWidth={1.8} aria-hidden />
                  {t(label)}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      {error ? (
        <p role="alert" className="shrink-0 px-3 pb-2 text-[11.5px] text-[var(--destructive,var(--foreground))]">
          {t("The notebook could not be saved. Your edits stay on screen.")}
        </p>
      ) : null}
    </div>
  );
}

function SaveBadge({
  state,
  label,
  onRetry,
}: {
  state: SaveState;
  label: (key: string) => string;
  onRetry?: () => void;
}) {
  if (state === "idle") return null;
  if (state === "error") {
    return (
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex shrink-0 items-center gap-1 rounded-md border border-[color-mix(in_srgb,var(--border)_60%,transparent)] px-2 py-1 text-[10.5px] font-medium text-[var(--destructive,var(--foreground))] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_60%,transparent)]"
      >
        <RefreshCw size={11} strokeWidth={2} />
        {label("Retry save")}
      </button>
    );
  }
  return (
    <span className="inline-flex shrink-0 items-center gap-1 text-[10.5px] text-[var(--muted-foreground)]">
      {state === "saving" ? (
        <>
          <Loader2 size={11} className="animate-spin" />
          {label("Saving…")}
        </>
      ) : (
        <>
          <Check size={11} strokeWidth={2.2} />
          {label("Saved")}
        </>
      )}
    </span>
  );
}

interface CellCardProps {
  cell: NotebookCell;
  index: number;
  total: number;
  run?: CellRun;
  tag?: NotebookTag;
  dragging: boolean;
  dragOver: boolean;
  onDragStart: () => void;
  onDragOver: () => void;
  onDragEnd: () => void;
  onDrop: () => void;
  onUploadImage?: (file: File) => Promise<string>;
  onChange: (patch: Partial<NotebookCell>) => void;
  onTagChange: (tag: NotebookTag | null) => void;
  onRun: () => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}

const CELL_BUTTON =
  "inline-flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_75%,transparent)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:pointer-events-none disabled:opacity-30";

function CellKindIcon({
  kind,
  className,
}: {
  kind: NotebookCell["kind"];
  className?: string;
}) {
  const Icon =
    kind === "code" ? SquareTerminal : kind === "geogebra" ? Shapes : FileText;
  return (
    <Icon
      size={14}
      strokeWidth={1.8}
      aria-hidden
      className={className}
    />
  );
}

function CellCard({
  cell,
  index,
  total,
  run,
  tag,
  dragging,
  dragOver,
  onDragStart,
  onDragOver,
  onDragEnd,
  onDrop,
  onUploadImage,
  onChange,
  onTagChange,
  onRun,
  onMove,
  onRemove,
}: CellCardProps) {
  const { t } = useTranslation();
  const rows = Math.min(
    24,
    Math.max(cell.kind === "markdown" ? 3 : 2, cell.source.split("\n").length),
  );
  // One control per cell: edit the source, see both side by side, or only the
  // preview. A cell with content opens on its rendered form, an empty one on
  // the editor.
  const [mode, setMode] = useState<"edit" | "split" | "preview">(
    cell.kind === "markdown" ? "edit" : cell.source.trim() ? "preview" : "edit",
  );
  const split = mode === "split";
  const [splitRatio, setSplitRatio] = useState(0.5);
  const splitRef = useRef<HTMLDivElement>(null);
  const [editingName, setEditingName] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const kindLabel = cellKindLabel(cell, t);
  const name = cell.name?.trim() ?? "";
  const running = run?.status === "running";

  // Insert a snippet at the caret, keeping the cursor after it. The textarea is
  // React-controlled, so the source change drives the value and the selection
  // is restored once the new value has painted.
  const insertAtCaret = useCallback(
    (snippet: string) => {
      const element = textareaRef.current;
      const value = cell.source;
      if (!element) {
        const spacer = value && !value.endsWith("\n") ? "\n" : "";
        onChange({ source: `${value}${spacer}${snippet}\n` });
        return;
      }
      const start = element.selectionStart ?? value.length;
      const end = element.selectionEnd ?? value.length;
      onChange({ source: value.slice(0, start) + snippet + value.slice(end) });
      requestAnimationFrame(() => {
        element.focus();
        const caret = start + snippet.length;
        element.setSelectionRange(caret, caret);
      });
    },
    [cell.source, onChange],
  );

  // Paste or drop a file into a note: upload it and drop the Markdown in place.
  const attachFiles = useCallback(
    async (files: File[]) => {
      if (!onUploadImage || files.length === 0) return;
      setUploading(true);
      try {
        for (const file of files) {
          const url = await onUploadImage(file);
          const label = file.name || "file";
          insertAtCaret(
            file.type.startsWith("image/")
              ? `![${label}](${url})`
              : `[${label}](${url})`,
          );
        }
      } catch {
        // A failed upload leaves the note as it was; nothing is inserted.
      } finally {
        setUploading(false);
      }
    },
    [insertAtCaret, onUploadImage],
  );

  const onPasteFiles = useCallback(
    (event: ClipboardEvent<HTMLTextAreaElement>) => {
      const files = Array.from(event.clipboardData?.files ?? []);
      if (files.length === 0 || !onUploadImage) return;
      event.preventDefault();
      void attachFiles(files);
    },
    [attachFiles, onUploadImage],
  );

  const onDropFiles = useCallback(
    (event: DragEvent<HTMLTextAreaElement>) => {
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length === 0 || !onUploadImage) return;
      // Keep the cell-reorder drop handler on the card out of this.
      event.preventDefault();
      event.stopPropagation();
      void attachFiles(files);
    },
    [attachFiles, onUploadImage],
  );

  const onDragOverFiles = useCallback(
    (event: DragEvent<HTMLTextAreaElement>) => {
      if (onUploadImage && event.dataTransfer?.types?.includes("Files")) {
        event.preventDefault();
        event.stopPropagation();
      }
    },
    [onUploadImage],
  );

  // Drag the middle of a split cell to trade width between editor and preview.
  const startSplitDrag = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const container = splitRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const onMove = (moveEvent: PointerEvent) => {
      if (!rect.width) return;
      const ratio = (moveEvent.clientX - rect.left) / rect.width;
      setSplitRatio(Math.min(0.8, Math.max(0.2, ratio)));
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const closeOnOutside = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [menuOpen]);

  return (
    <div
      ref={cardRef}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        onDragOver();
      }}
      onDrop={(event) => {
        event.preventDefault();
        onDrop();
      }}
      className={`overflow-hidden rounded-2xl border bg-[var(--card)] shadow-sm transition-[border-color,box-shadow,opacity] ${
        dragOver
          ? "border-[var(--primary)] shadow-md"
          : "border-[color-mix(in_srgb,var(--border)_60%,transparent)] hover:border-[color-mix(in_srgb,var(--border)_95%,transparent)] focus-within:border-[color-mix(in_srgb,var(--primary)_35%,var(--border))] focus-within:shadow-md"
      } ${dragging ? "opacity-45" : ""}`}
    >
      <div className="flex items-start gap-1.5 px-2.5 pb-1 pt-2">
        <button
          type="button"
          draggable
          onDragStart={(event) => {
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", cell.id);
            if (cardRef.current) {
              event.dataTransfer.setDragImage(cardRef.current, 24, 20);
            }
            onDragStart();
          }}
          onDragEnd={onDragEnd}
          aria-label={t("Drag to reorder")}
          title={t("Drag to reorder")}
          className="-ml-1 mt-[3px] inline-flex h-7 w-5 shrink-0 cursor-grab items-center justify-center rounded-md text-[var(--muted-foreground)] opacity-60 transition hover:bg-[color-mix(in_srgb,var(--muted)_70%,transparent)] hover:opacity-100 active:cursor-grabbing"
        >
          <GripVertical size={14} strokeWidth={1.8} />
        </button>
        <CellKindIcon
          kind={cell.kind}
          className="mt-[5px] shrink-0 text-[var(--muted-foreground)]"
        />
        <div className="min-w-0 flex-1">
          {editingName ? (
            <input
              autoFocus
              value={cell.name ?? ""}
              onChange={(event) => onChange({ name: event.target.value })}
              onBlur={() => setEditingName(false)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === "Escape") {
                  setEditingName(false);
                }
              }}
              placeholder={kindLabel}
              aria-label={t("Cell name")}
              className="block w-full min-w-0 truncate rounded-md border border-[var(--border)] bg-transparent px-1 py-0.5 text-[13px] font-medium text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)] focus:border-[var(--primary)]"
            />
          ) : (
            <button
              type="button"
              onClick={() => setEditingName(true)}
              title={t("Rename cell")}
              className="block w-full min-w-0 truncate rounded-md px-1 py-0.5 text-left text-[13px] font-medium text-[var(--foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_60%,transparent)]"
            >
              {name || kindLabel}
            </button>
          )}
          {name ? (
            <div className="truncate px-1 text-[10px] font-medium text-[var(--muted-foreground)]">
              {kindLabel}
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <NotebookTagControl tag={tag} onChange={onTagChange} />
          {cell.kind === "markdown" && onUploadImage ? (
            <button
              type="button"
              className={CELL_BUTTON}
              onClick={() => fileInputRef.current?.click()}
              aria-label={t("Add image")}
              title={t("Add image")}
              disabled={uploading}
            >
              {uploading ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <ImagePlus size={14} strokeWidth={1.9} />
              )}
            </button>
          ) : null}
          {cell.kind === "code" ? (
            <>
              <select
                value={normalizeCellLanguage(cell.language)}
                onChange={(event) =>
                  onChange({ language: normalizeCellLanguage(event.target.value) })
                }
                aria-label={t("Language")}
                title={t("Language")}
                className="h-7 max-w-[76px] cursor-pointer rounded-lg bg-transparent px-1 text-[11px] font-medium text-[var(--muted-foreground)] outline-none transition-colors hover:text-[var(--foreground)]"
              >
                {CODE_LANGUAGE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {t(option.label)}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={onRun}
                disabled={!cell.source.trim() || running}
                aria-label={t("Run cell")}
                title={t("Run cell")}
                className="inline-flex h-7 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-2.5 text-[11.5px] font-semibold text-[var(--primary-foreground)] shadow-sm transition hover:brightness-95 active:brightness-90 disabled:pointer-events-none disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
              >
                {running ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <Play size={12} strokeWidth={2.2} fill="currentColor" />
                )}
                {t(running ? "Running…" : "Run cell")}
              </button>
            </>
          ) : null}
          <div className="flex shrink-0 items-center gap-0.5 rounded-lg border border-[color-mix(in_srgb,var(--border)_55%,transparent)] p-0.5">
            {(["edit", "split", "preview"] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setMode(value)}
                aria-pressed={mode === value}
                title={t(value === "edit" ? "Edit" : value === "split" ? "Split" : "Preview")}
                className={`rounded-md px-1.5 py-0.5 text-[10.5px] font-medium transition-colors ${
                  mode === value
                    ? "bg-[color-mix(in_srgb,var(--muted)_85%,transparent)] text-[var(--foreground)]"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                {t(value === "edit" ? "Edit" : value === "split" ? "Split" : "Preview")}
              </button>
            ))}
          </div>
          <div ref={menuRef} className="relative">
            <button
              type="button"
              className={CELL_BUTTON}
              onClick={() => setMenuOpen((open) => !open)}
              aria-label={t("More actions")}
              title={t("More actions")}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
            >
              <MoreHorizontal size={15} strokeWidth={1.9} />
            </button>
            {menuOpen ? (
              <div
                role="menu"
                className="absolute right-0 top-full z-30 mt-1 w-40 rounded-xl border border-[var(--border)] bg-[var(--card)] p-1 shadow-xl"
              >
                <button
                  type="button"
                  role="menuitem"
                  disabled={index === 0}
                  onClick={() => {
                    onMove(-1);
                    setMenuOpen(false);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12px] text-[var(--foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_75%,transparent)] disabled:pointer-events-none disabled:opacity-35"
                >
                  <ArrowUp size={13} strokeWidth={1.9} />
                  {t("Move up")}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  disabled={index === total - 1}
                  onClick={() => {
                    onMove(1);
                    setMenuOpen(false);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12px] text-[var(--foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_75%,transparent)] disabled:pointer-events-none disabled:opacity-35"
                >
                  <ArrowDown size={13} strokeWidth={1.9} />
                  {t("Move down")}
                </button>
                <div className="my-1 h-px bg-[color-mix(in_srgb,var(--border)_55%,transparent)]" />
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    onRemove();
                    setMenuOpen(false);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12px] text-[var(--destructive,var(--foreground))] transition-colors hover:bg-[color-mix(in_srgb,var(--destructive)_10%,transparent)]"
                >
                  <Trash2 size={13} strokeWidth={1.9} />
                  {t("Delete cell")}
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          void attachFiles(files);
        }}
      />

      {split ? (
        <div
          ref={splitRef}
          className="nb-split"
          style={{ "--nb-split": String(splitRatio) } as CSSProperties}
        >
          <div className="min-w-0">
            <textarea
              ref={cell.kind === "markdown" ? textareaRef : undefined}
              value={cell.source}
              rows={rows}
              spellCheck={false}
              onPaste={cell.kind === "markdown" ? onPasteFiles : undefined}
              onDrop={cell.kind === "markdown" ? onDropFiles : undefined}
              onDragOver={cell.kind === "markdown" ? onDragOverFiles : undefined}
              onChange={(event) => onChange({ source: event.target.value })}
              placeholder={
                cell.kind === "geogebra"
                  ? t("GeoGebra commands, one per line.")
                  : cell.kind === "code"
                    ? t("print('hello')")
                    : t("Write a note, with $math$ in Markdown.")
              }
              className={`block h-full w-full resize-y bg-transparent px-3.5 py-2.5 text-[var(--foreground)] outline-none placeholder:text-[color-mix(in_srgb,var(--muted-foreground)_55%,transparent)] ${
                cell.kind === "code" || cell.kind === "geogebra"
                  ? "font-mono text-[12.5px] leading-relaxed"
                  : "text-[13.5px] leading-6"
              }`}
            />
          </div>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label={t("Split")}
            className="nb-split-divider"
            onPointerDown={startSplitDrag}
          />
          <div className="min-w-0 overflow-auto px-3.5 py-2.5">
            {cell.kind === "geogebra" ? (
              <BoardCellBody script={cell.source} />
            ) : cell.kind === "code" ? (
              cell.source.trim() ? (
                <RichCodeBlock
                  raw={cell.source}
                  lang={normalizeCellLanguage(cell.language)}
                />
              ) : (
                <p className="text-[12px] text-[var(--muted-foreground)]">
                  {t("(empty)")}
                </p>
              )
            ) : cell.source.trim() ? (
              <div className="text-[13.5px] leading-relaxed">
                <RichMarkdownRenderer content={cell.source} enableMath enableCode enableMermaid />
              </div>
            ) : (
              <p className="text-[12px] text-[var(--muted-foreground)]">
                {t("(empty)")}
              </p>
            )}
          </div>
        </div>
      ) : cell.kind === "geogebra" && mode === "preview" ? (
        <BoardCellBody script={cell.source} />
      ) : cell.kind === "code" && mode === "preview" && cell.source.trim() ? (
        <div className="px-2.5 pb-1 pt-1.5">
          <RichCodeBlock
            raw={cell.source}
            lang={normalizeCellLanguage(cell.language)}
          />
        </div>
      ) : cell.kind === "markdown" && mode === "preview" && cell.source.trim() ? (
        <div className="px-3.5 pb-3 pt-1.5 text-[13.5px] leading-relaxed">
          <RichMarkdownRenderer content={cell.source} enableMath enableCode enableMermaid />
        </div>
      ) : (
        <textarea
          ref={cell.kind === "markdown" ? textareaRef : undefined}
          value={cell.source}
          rows={rows}
          spellCheck={false}
          onPaste={cell.kind === "markdown" ? onPasteFiles : undefined}
          onDrop={cell.kind === "markdown" ? onDropFiles : undefined}
          onDragOver={cell.kind === "markdown" ? onDragOverFiles : undefined}
          onChange={(event) => onChange({ source: event.target.value })}
          placeholder={
            cell.kind === "geogebra"
              ? t("GeoGebra commands, one per line.")
              : cell.kind === "code"
                ? t("print('hello')")
                : t("Write a note, with $math$ in Markdown.")
          }
          className={`block w-full resize-y bg-transparent px-3.5 py-2 text-[var(--foreground)] outline-none placeholder:text-[color-mix(in_srgb,var(--muted-foreground)_55%,transparent)] ${
            cell.kind === "code" || cell.kind === "geogebra"
              ? "font-mono text-[12.5px] leading-relaxed"
              : "text-[13.5px] leading-6"
          }`}
        />
      )}

      {run ? <CellOutput run={run} /> : null}
    </div>
  );
}

/**
 * A GeoGebra board sized to the panel. A blank board is editable (the learner
 * draws on it); a scripted one shows a clean figure. Drawn changes are not
 * persisted — only the script is.
 */
function BoardCellBody({ script }: { script: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () =>
      setSize({ width: Math.max(280, Math.floor(el.clientWidth) - 2), height: 340 });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className="w-full px-1 py-1">
      {size ? (
        <Geogebra
          script={script}
          editable={!script.trim()}
          width={size.width}
          height={size.height}
        />
      ) : null}
    </div>
  );
}

function CellOutput({ run }: { run: CellRun }) {
  const { t } = useTranslation();

  if (run.status === "running") {
    return (
      <div className="flex items-center gap-2 border-t border-[color-mix(in_srgb,var(--border)_40%,transparent)] px-3.5 py-2.5 text-[11.5px] text-[var(--muted-foreground)]">
        <Loader2 size={12} className="animate-spin" />
        {t("Running…")}
      </div>
    );
  }

  if (run.status === "error") {
    return (
      <div className="border-t border-[color-mix(in_srgb,var(--border)_40%,transparent)] px-3.5 py-2.5 text-[11.5px] text-[var(--destructive,var(--foreground))]">
        {run.message}
      </div>
    );
  }

  const { run: result } = run;
  const failed = Boolean(result.error) || result.exit_code !== 0 || result.timed_out;

  return (
    <div className="border-t border-[color-mix(in_srgb,var(--border)_40%,transparent)] bg-[color-mix(in_srgb,var(--muted)_24%,var(--card))] px-3.5 py-2.5 text-[12.5px]">
      {result.error ? (
        <p className="whitespace-pre-wrap text-[var(--destructive,var(--foreground))]">
          {result.error}
        </p>
      ) : null}

      {result.stdout.trim() ? (
        <RichMarkdownRenderer content={result.stdout} enableMath enableCode enableMermaid />
      ) : null}

      {result.stderr.trim() ? (
        <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap font-mono text-[11.5px] text-[var(--muted-foreground)]">
          {result.stderr}
        </pre>
      ) : null}

      {result.artifacts.map((artifact) => {
        const src = apiUrl(artifact.url);
        if (artifact.mime_type.startsWith("image/")) {
          return (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={artifact.relative_path}
              src={src}
              alt={artifact.filename}
              className="mt-2 max-w-full rounded-lg border border-[color-mix(in_srgb,var(--border)_45%,transparent)]"
            />
          );
        }
        if (artifact.mime_type.startsWith("video/")) {
          return (
            <video
              key={artifact.relative_path}
              src={src}
              controls
              className="mt-2 max-w-full rounded-lg border border-[color-mix(in_srgb,var(--border)_45%,transparent)]"
            />
          );
        }
        if (artifact.mime_type.startsWith("audio/")) {
          return (
            <audio key={artifact.relative_path} src={src} controls className="mt-2 w-full" />
          );
        }
        return (
          <a
            key={artifact.relative_path}
            href={src}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 block truncate text-[12px] text-[var(--primary)] underline"
          >
            {artifact.filename}
          </a>
        );
      })}

      {failed || result.stdout.trim() || result.stderr.trim() ? null : (
        <p className="text-[11.5px] text-[var(--muted-foreground)]">
          {t("No output")}
        </p>
      )}

      {failed && !result.error ? (
        <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
          {t("Exit code {{code}}", { code: result.exit_code })}
          {result.timed_out ? ` · ${t("timed out")}` : ""}
        </p>
      ) : null}
    </div>
  );
}
