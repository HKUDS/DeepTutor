"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Archive,
  Check,
  Compass,
  History,
  Loader2,
  Pencil,
  Pin,
  PinOff,
  Plus,
  RotateCcw,
  Sparkles,
  X,
} from "lucide-react";

import { useModalDialog } from "@/hooks/useModalDialog";
import {
  archiveStrategyNote,
  createStrategyNote,
  editStrategyNote,
  fetchStrategyNoteHistory,
  fetchStrategyNotes,
  restoreStrategyNote,
  rollbackStrategyNote,
  type StrategyNote,
  type StrategyNoteRevision,
} from "@/lib/learning-api";

/**
 * The learner-visible surface for the tutor's teaching strategy.
 *
 * A mastery path accumulates short notes about how *this* learner is best
 * taught — learned from their questions, their likes and the tutor's own
 * observations. This panel shows them, attributes each one (tutor-learned or
 * learner-written), and lets the learner edit, pin, archive, restore or roll
 * back. Nothing here is ever deleted; archiving keeps the history.
 */
export function MasteryStrategyPanel({
  pathId,
  onClose,
}: {
  pathId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const dialogRef = useModalDialog(onClose);

  const [notes, setNotes] = useState<StrategyNote[]>([]);
  const [archived, setArchived] = useState<StrategyNote[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<{ noteId: string; body: string } | null>(
    null,
  );
  const [history, setHistory] = useState<{
    noteId: string;
    entries: StrategyNoteRevision[];
  } | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const result = await fetchStrategyNotes(pathId, true);
      const all = result.notes ?? [];
      setNotes(all.filter((note) => note.status !== "archived"));
      setArchived(all.filter((note) => note.status === "archived"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [pathId]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = useCallback(
    async (action: () => Promise<unknown>) => {
      setBusy(true);
      setError("");
      try {
        await action();
        await load();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  const addNote = useCallback(() => {
    const body = draft.trim();
    if (!body || busy) return;
    void run(async () => {
      await createStrategyNote(pathId, { body });
      setDraft("");
    });
  }, [busy, draft, pathId, run]);

  const saveEdit = useCallback(() => {
    if (!editing || busy) return;
    const body = editing.body.trim();
    if (!body) return;
    void run(async () => {
      await editStrategyNote(pathId, editing.noteId, { body });
      setEditing(null);
    });
  }, [busy, editing, pathId, run]);

  const openHistory = useCallback(
    async (noteId: string) => {
      setError("");
      try {
        const result = await fetchStrategyNoteHistory(pathId, noteId);
        setHistory({ noteId, entries: result.history ?? [] });
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [pathId],
  );

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="strategy-panel-title"
      tabIndex={-1}
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-3 backdrop-blur-sm sm:p-6"
    >
      <div className="flex max-h-full w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--background)] shadow-2xl">
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-[var(--border)] bg-[var(--card)] px-4 py-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--primary)]/10 text-[var(--primary)]">
              <Compass className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <h2
                id="strategy-panel-title"
                className="text-sm font-semibold text-[var(--foreground)]"
              >
                {t("Learning strategy")}
              </h2>
              <p className="mt-0.5 text-[12px] leading-5 text-[var(--muted-foreground)]">
                {t(
                  "How the tutor has learned to teach you. Edit or remove any note; removing archives it and you can restore it.",
                )}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("Close")}
            className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4">
          {error ? (
            <p className="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-[12.5px] text-red-600">
              {error}
            </p>
          ) : null}

          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
            </div>
          ) : (
            <>
              {notes.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-10 text-center">
                  <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[var(--muted)]/60">
                    <Sparkles className="h-5 w-5 text-[var(--muted-foreground)]" />
                  </span>
                  <p className="max-w-sm text-[13px] leading-6 text-[var(--muted-foreground)]">
                    {t(
                      "No strategy notes yet. Notes the tutor learns from your questions and likes will appear here.",
                    )}
                  </p>
                </div>
              ) : (
                <ul className="flex flex-col gap-2">
                  {notes.map((note) => (
                    <StrategyNoteRow
                      key={note.note_id}
                      note={note}
                      busy={busy}
                      editing={editing?.noteId === note.note_id ? editing : null}
                      onStartEdit={() =>
                        setEditing({ noteId: note.note_id, body: note.body })
                      }
                      onEditChange={(body) =>
                        setEditing({ noteId: note.note_id, body })
                      }
                      onSaveEdit={saveEdit}
                      onCancelEdit={() => setEditing(null)}
                      onTogglePin={() =>
                        void run(() =>
                          editStrategyNote(pathId, note.note_id, {
                            body: note.body,
                            pinned: !note.pinned,
                          }),
                        )
                      }
                      onArchive={() =>
                        void run(() => archiveStrategyNote(pathId, note.note_id))
                      }
                      onHistory={() => void openHistory(note.note_id)}
                    />
                  ))}
                </ul>
              )}

              {history ? (
                <div className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-[12.5px] font-medium text-[var(--foreground)]">
                      {t("History")}
                    </span>
                    <button
                      type="button"
                      onClick={() => setHistory(null)}
                      aria-label={t("Close")}
                      className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <ul className="flex flex-col gap-1.5">
                    {history.entries.map((entry, index) => (
                      <li
                        key={entry.revision}
                        className="flex items-start justify-between gap-2 rounded-lg bg-[var(--muted)]/40 px-2.5 py-2"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-[12.5px] text-[var(--foreground)]">
                            {entry.body}
                          </p>
                          <span className="text-[11px] text-[var(--muted-foreground)]">
                            {t("Revision")} {entry.revision}
                          </span>
                        </div>
                        {index > 0 ? (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() =>
                              void run(async () => {
                                await rollbackStrategyNote(
                                  pathId,
                                  history.noteId,
                                  entry.revision,
                                );
                                setHistory(null);
                              })
                            }
                            className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11.5px] text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-40"
                          >
                            <RotateCcw className="h-3 w-3" />
                            {t("Restore")}
                          </button>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {archived.length > 0 ? (
                <div className="mt-4">
                  <p className="mb-1.5 text-[11.5px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                    {t("Archived")}
                  </p>
                  <ul className="flex flex-col gap-1.5">
                    {archived.map((note) => (
                      <li
                        key={note.note_id}
                        className="flex items-start justify-between gap-2 rounded-lg border border-dashed border-[var(--border)] px-2.5 py-2"
                      >
                        <span className="min-w-0 truncate text-[12.5px] text-[var(--muted-foreground)] line-through">
                          {note.body}
                        </span>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            void run(() =>
                              restoreStrategyNote(pathId, note.note_id),
                            )
                          }
                          className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11.5px] text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-40"
                        >
                          <RotateCcw className="h-3 w-3" />
                          {t("Restore")}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2 border-t border-[var(--border)] bg-[var(--card)] px-4 py-3">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addNote();
              }
            }}
            placeholder={t("Add a note about how you want to be taught")}
            aria-label={t("Add a note about how you want to be taught")}
            maxLength={400}
            className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
          />
          <button
            type="button"
            onClick={addNote}
            disabled={busy || !draft.trim()}
            className="flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-2 text-[13px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" />
            {t("Add")}
          </button>
        </div>
      </div>
    </div>
  );
}

function StrategyNoteRow({
  note,
  busy,
  editing,
  onStartEdit,
  onEditChange,
  onSaveEdit,
  onCancelEdit,
  onTogglePin,
  onArchive,
  onHistory,
}: {
  note: StrategyNote;
  busy: boolean;
  editing: { noteId: string; body: string } | null;
  onStartEdit: () => void;
  onEditChange: (body: string) => void;
  onSaveEdit: () => void;
  onCancelEdit: () => void;
  onTogglePin: () => void;
  onArchive: () => void;
  onHistory: () => void;
}) {
  const { t } = useTranslation();
  const isEditing = editing !== null;
  return (
    <li className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5">
      {isEditing ? (
        <div className="flex flex-col gap-2">
          <textarea
            value={editing.body}
            onChange={(event) => onEditChange(event.target.value)}
            maxLength={400}
            rows={2}
            aria-label={t("Edit note")}
            className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-2 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]"
          />
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={onCancelEdit}
              className="rounded-md px-2.5 py-1 text-[12.5px] text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
            >
              {t("Cancel")}
            </button>
            <button
              type="button"
              onClick={onSaveEdit}
              disabled={busy || !editing.body.trim()}
              className="flex items-center gap-1 rounded-md bg-[var(--primary)] px-2.5 py-1 text-[12.5px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
            >
              <Check className="h-3.5 w-3.5" />
              {t("Save")}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-[13px] leading-6 text-[var(--foreground)]">
              {note.body}
            </p>
            <span className="mt-1 inline-block rounded-full bg-[var(--muted)]/60 px-2 py-0.5 text-[11px] text-[var(--muted-foreground)]">
              {note.created_by === "learner"
                ? t("Added by you")
                : t("Learned by the tutor")}
              {note.pinned ? ` · ${t("Pinned")}` : ""}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-0.5">
            <button
              type="button"
              onClick={onTogglePin}
              disabled={busy}
              aria-label={note.pinned ? t("Unpin") : t("Pin")}
              className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-40"
            >
              {note.pinned ? (
                <PinOff className="h-3.5 w-3.5" />
              ) : (
                <Pin className="h-3.5 w-3.5" />
              )}
            </button>
            <button
              type="button"
              onClick={onStartEdit}
              disabled={busy}
              aria-label={t("Edit")}
              className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-40"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={onHistory}
              disabled={busy}
              aria-label={t("History")}
              className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-40"
            >
              <History className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={onArchive}
              disabled={busy}
              aria-label={t("Archive")}
              className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)] disabled:opacity-40"
            >
              <Archive className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </li>
  );
}
