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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Play, Plus, Trash2, ArrowUp, ArrowDown, Loader2, Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import RichMarkdownRenderer from "@/components/common/RichMarkdownRenderer";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import { apiUrl } from "@/lib/api";
import { getSession } from "@/lib/session-api";
import { createNote, getNote, saveNote } from "@/lib/notes-api";
import {
  CODE_LANGUAGE_OPTIONS,
  createCodeCell,
  createMarkdownCell,
  defaultNotebookCells,
  normalizeCellLanguage,
  parseNotebookMarkdown,
  serializeNotebookMarkdown,
  type NotebookCell,
} from "@/lib/notebook-cells";
import {
  runNotebookCell,
  type NotebookCellRun,
} from "@/lib/notebook-lab-api";

interface ChatNotebookTabProps {
  sessionId: string | null;
}

type CellRun =
  | { status: "running" }
  | { status: "done"; run: NotebookCellRun }
  | { status: "error"; message: string };

type SaveState = "idle" | "saving" | "saved" | "error";

const POINTER_PREFIX = "dt:chat-notebook:";
const AUTOSAVE_MS = 900;

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

export default function ChatNotebookTab({ sessionId }: ChatNotebookTabProps) {
  const { t } = useTranslation();
  const auth = useAuthStatus();
  const owner =
    !auth.loading && auth.statusAvailable
      ? auth.enabled
        ? auth.userId
        : "local"
      : null;

  const [ready, setReady] = useState(false);
  const [cells, setCells] = useState<NotebookCell[]>(() =>
    defaultNotebookCells(),
  );
  const [runs, setRuns] = useState<Record<string, CellRun>>({});
  const [previewing, setPreviewing] = useState<Set<string>>(() => new Set());
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [error, setError] = useState("");

  const docIdRef = useRef<string | null>(null);
  const revisionRef = useRef(0);
  const pointerKeyRef = useRef<string>("");
  const notebookKeyRef = useRef<string>("default");
  const lastSavedRef = useRef<string>("");
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

      pointIdRef.current = pointId;
      notebookKeyRef.current = sessionId || "default";
      const key = pointerKey(owner, sessionId, pointId || pathId);
      pointerKeyRef.current = key;

      const pointer = readPointer(key);
      if (pointer) {
        try {
          const page = await getNote(pointer.id);
          if (cancelled) return;
          docIdRef.current = page.id;
          revisionRef.current = page.revision;
          const markdown = page.content ?? "";
          lastSavedRef.current = markdown;
          setCells(parseNotebookMarkdown(markdown));
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
      setCells(defaultNotebookCells());
      setReady(true);
    })();

    return () => {
      cancelled = true;
    };
  }, [owner, sessionId]);

  const persist = useCallback(async (nextCells: NotebookCell[]) => {
    const markdown = serializeNotebookMarkdown(nextCells);
    if (markdown === lastSavedRef.current) return;
    setSaveState("saving");
    try {
      const title = t("Notebook");
      if (docIdRef.current) {
        const page = await saveNote(docIdRef.current, {
          title,
          content: markdown,
          expected_revision: revisionRef.current,
        });
        revisionRef.current = page.revision;
      } else {
        const page = await createNote(title, null, markdown);
        docIdRef.current = page.id;
        revisionRef.current = page.revision;
      }
      lastSavedRef.current = markdown;
      if (pointerKeyRef.current) {
        writePointer(pointerKeyRef.current, {
          id: docIdRef.current as string,
          revision: revisionRef.current,
        });
      }
      setSaveState("saved");
      setError("");
    } catch (err) {
      setSaveState("error");
      setError(String(err instanceof Error ? err.message : err));
    }
  }, [t]);

  // Debounced autosave. Never fires before the page has loaded, so restoring a
  // page cannot immediately rewrite it.
  useEffect(() => {
    if (!ready || !owner) return;
    const markdown = serializeNotebookMarkdown(cells);
    if (markdown === lastSavedRef.current) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      void persist(cells);
    }, AUTOSAVE_MS);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [cells, ready, owner, persist]);

  const updateCell = useCallback((id: string, patch: Partial<NotebookCell>) => {
    setCells((prev) =>
      prev.map((cell) => (cell.id === id ? { ...cell, ...patch } : cell)),
    );
  }, []);

  const addCell = useCallback((kind: NotebookCell["kind"]) => {
    setCells((prev) => [
      ...prev,
      kind === "code" ? createCodeCell() : createMarkdownCell(),
    ]);
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

  const togglePreview = useCallback((id: string) => {
    setPreviewing((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

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
      <div className="flex shrink-0 items-center gap-2 border-b border-[color-mix(in_srgb,var(--border)_45%,transparent)] px-4 py-2.5">
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12.5px] font-semibold text-[var(--foreground)]">
            {t("Notebook")}
          </div>
          <div className="truncate text-[10.5px] text-[var(--muted-foreground)]">
            {pointIdRef.current
              ? t("Bound to knowledge point {{id}}", {
                  id: pointIdRef.current,
                })
              : t("Notes and runnable code, kept with this conversation.")}
          </div>
        </div>
        <SaveBadge state={saveState} label={t} />
        {hasCode ? (
          <button
            type="button"
            onClick={() => void runAll()}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-[color-mix(in_srgb,var(--border)_55%,transparent)] px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <Play size={11} strokeWidth={2} />
            {t("Run all")}
          </button>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {!ready ? (
          <div className="flex items-center gap-2 p-3 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 size={13} className="animate-spin" />
            {t("Loading notebook…")}
          </div>
        ) : (
          cells.map((cell, index) => (
            <CellCard
              key={cell.id}
              cell={cell}
              index={index}
              total={cells.length}
              run={runs[cell.id]}
              previewing={previewing.has(cell.id)}
              onTogglePreview={() => togglePreview(cell.id)}
              onChange={(patch) => updateCell(cell.id, patch)}
              onRun={() => void runCell(cell)}
              onMove={(delta) => moveCell(cell.id, delta)}
              onRemove={() => removeCell(cell.id)}
            />
          ))
        )}

        <div className="flex gap-2 pt-1">
          <button
            type="button"
            onClick={() => addCell("markdown")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-[color-mix(in_srgb,var(--border)_70%,transparent)] px-2.5 py-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <Plus size={13} strokeWidth={2} />
            {t("Note cell")}
          </button>
          <button
            type="button"
            onClick={() => addCell("code")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-[color-mix(in_srgb,var(--border)_70%,transparent)] px-2.5 py-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <Plus size={13} strokeWidth={2} />
            {t("Code cell")}
          </button>
        </div>

        {error ? (
          <p role="alert" className="px-1 text-[11.5px] text-[var(--destructive,var(--foreground))]">
            {t("The notebook could not be saved. Your edits stay on screen.")}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function SaveBadge({
  state,
  label,
}: {
  state: SaveState;
  label: (key: string) => string;
}) {
  if (state === "idle") return null;
  return (
    <span className="inline-flex shrink-0 items-center gap-1 text-[10.5px] text-[var(--muted-foreground)]">
      {state === "saving" ? (
        <>
          <Loader2 size={11} className="animate-spin" />
          {label("Saving…")}
        </>
      ) : state === "saved" ? (
        <>
          <Check size={11} strokeWidth={2.2} />
          {label("Saved")}
        </>
      ) : (
        label("Not saved")
      )}
    </span>
  );
}

interface CellCardProps {
  cell: NotebookCell;
  index: number;
  total: number;
  run?: CellRun;
  previewing: boolean;
  onTogglePreview: () => void;
  onChange: (patch: Partial<NotebookCell>) => void;
  onRun: () => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}

const CELL_BUTTON =
  "inline-flex h-6 w-6 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_70%,transparent)] hover:text-[var(--foreground)] disabled:pointer-events-none disabled:opacity-30";

function CellCard({
  cell,
  index,
  total,
  run,
  previewing,
  onTogglePreview,
  onChange,
  onRun,
  onMove,
  onRemove,
}: CellCardProps) {
  const { t } = useTranslation();
  const rows = Math.min(24, Math.max(2, cell.source.split("\n").length));

  return (
    <div className="overflow-hidden rounded-xl border border-[color-mix(in_srgb,var(--border)_55%,transparent)] bg-[var(--card)]">
      <div className="flex items-center gap-1 border-b border-[color-mix(in_srgb,var(--border)_35%,transparent)] px-2 py-1">
        <span className="flex-1 pl-1 text-[10.5px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {cell.kind === "code" ? t("Code") : t("Note")}
        </span>
        {cell.kind === "markdown" ? (
          <button type="button" className={CELL_BUTTON} onClick={onTogglePreview} aria-label={t(previewing ? "Edit" : "Preview")}>
            <span className="text-[10.5px] font-medium">
              {t(previewing ? "Edit" : "Preview")}
            </span>
          </button>
        ) : (
          <>
            <select
              value={normalizeCellLanguage(cell.language)}
              onChange={(event) =>
                onChange({ language: normalizeCellLanguage(event.target.value) })
              }
              aria-label={t("Language")}
              className="h-6 rounded-md bg-transparent px-1 text-[11px] text-[var(--foreground)] outline-none"
            >
              {CODE_LANGUAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {t(option.label)}
                </option>
              ))}
            </select>
            <button
              type="button"
              className={CELL_BUTTON}
              onClick={onRun}
              disabled={!cell.source.trim() || run?.status === "running"}
              aria-label={t("Run cell")}
            >
              {run?.status === "running" ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Play size={13} strokeWidth={2} />
              )}
            </button>
          </>
        )}
        <button
          type="button"
          className={CELL_BUTTON}
          onClick={() => onMove(-1)}
          disabled={index === 0}
          aria-label={t("Move up")}
        >
          <ArrowUp size={13} strokeWidth={2} />
        </button>
        <button
          type="button"
          className={CELL_BUTTON}
          onClick={() => onMove(1)}
          disabled={index === total - 1}
          aria-label={t("Move down")}
        >
          <ArrowDown size={13} strokeWidth={2} />
        </button>
        <button
          type="button"
          className={CELL_BUTTON}
          onClick={onRemove}
          aria-label={t("Delete cell")}
        >
          <Trash2 size={13} strokeWidth={2} />
        </button>
      </div>

      {cell.kind === "markdown" && previewing && cell.source.trim() ? (
        <div className="px-3 py-2.5 text-[13px]">
          <RichMarkdownRenderer content={cell.source} enableMath enableCode />
        </div>
      ) : (
        <textarea
          value={cell.source}
          rows={rows}
          spellCheck={false}
          onChange={(event) => onChange({ source: event.target.value })}
          placeholder={
            cell.kind === "code"
              ? t("print('hello')")
              : t("Write a note, with $math$ in Markdown.")
          }
          className="block w-full resize-y bg-transparent px-3 py-2.5 font-mono text-[12.5px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[color-mix(in_srgb,var(--muted-foreground)_60%,transparent)]"
        />
      )}

      {run ? <CellOutput run={run} /> : null}
    </div>
  );
}

function CellOutput({ run }: { run: CellRun }) {
  const { t } = useTranslation();

  if (run.status === "running") {
    return (
      <div className="flex items-center gap-2 border-t border-[color-mix(in_srgb,var(--border)_30%,transparent)] px-3 py-2 text-[11.5px] text-[var(--muted-foreground)]">
        <Loader2 size={12} className="animate-spin" />
        {t("Running…")}
      </div>
    );
  }

  if (run.status === "error") {
    return (
      <div className="border-t border-[color-mix(in_srgb,var(--border)_30%,transparent)] px-3 py-2 text-[11.5px] text-[var(--destructive,var(--foreground))]">
        {run.message}
      </div>
    );
  }

  const { run: result } = run;
  const failed = Boolean(result.error) || result.exit_code !== 0 || result.timed_out;

  return (
    <div className="border-t border-[color-mix(in_srgb,var(--border)_30%,transparent)] bg-[color-mix(in_srgb,var(--muted)_28%,var(--card))] px-3 py-2 text-[12.5px]">
      {result.error ? (
        <p className="whitespace-pre-wrap text-[var(--destructive,var(--foreground))]">
          {result.error}
        </p>
      ) : null}

      {result.stdout.trim() ? (
        <RichMarkdownRenderer content={result.stdout} enableMath enableCode />
      ) : null}

      {result.stderr.trim() ? (
        <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap font-mono text-[11.5px] text-[var(--muted-foreground)]">
          {result.stderr}
        </pre>
      ) : null}

      {result.artifacts.map((artifact) =>
        artifact.mime_type.startsWith("image/") ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={artifact.relative_path}
            src={apiUrl(artifact.url)}
            alt={artifact.filename}
            className="mt-2 max-w-full rounded-lg border border-[color-mix(in_srgb,var(--border)_45%,transparent)]"
          />
        ) : (
          <a
            key={artifact.relative_path}
            href={apiUrl(artifact.url)}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 block truncate text-[12px] text-[var(--primary)] underline"
          >
            {artifact.filename}
          </a>
        ),
      )}

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
