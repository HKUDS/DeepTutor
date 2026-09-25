"use client";

import {
  Check,
  Copy,
  Loader2,
  NotebookPen,
  Send,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { type NotebookSummary, listNotebooks } from "@/lib/notebook-api";
import { copyText } from "@/lib/clipboard";
import { notify } from "@/lib/notifications";
import {
  type OrganizedReadingNotes,
  type ReadingConversation,
  sendReadingToNotebook,
} from "@/lib/reading-workspace-api";

export function ModalShell({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-[var(--overlay)] p-4 backdrop-blur-[2px]">
      <div
        className={`w-full ${wide ? "max-w-3xl" : "max-w-md"} rounded-[22px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-2xl dark:border-[var(--border)] dark:bg-[var(--popover)]`}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-serif text-[19px] font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("Close")}
            className="flex size-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            <X size={14} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ConversationLinkDialog({
  conversations,
  current,
  onClose,
  onSave,
}: {
  conversations: ReadingConversation[];
  current: ReadingConversation;
  onClose: () => void;
  onSave: (ids: string[]) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<string[]>(
    current.linked_session_ids ?? [],
  );
  const [saving, setSaving] = useState(false);
  const candidates = conversations.filter(
    (row) => row.session_id !== current.session_id,
  );
  return (
    <ModalShell title={t("Link reading conversations")} onClose={onClose}>
      <p className="text-[11px] leading-relaxed text-[var(--muted-foreground)]">
        {t(
          "Linked conversations are passed explicitly as historical context. They remain separate and never appear in regular Chat history.",
        )}
      </p>
      <div className="mt-4 max-h-72 space-y-1 overflow-y-auto">
        {candidates.length ? (
          candidates.map((row) => {
            const checked = selected.includes(row.session_id);
            return (
              <button
                key={row.session_id}
                type="button"
                onClick={() =>
                  setSelected((values) =>
                    checked
                      ? values.filter((id) => id !== row.session_id)
                      : [...values, row.session_id],
                  )
                }
                className="flex w-full items-center gap-3 rounded-xl border border-[var(--border)] px-3 py-3 text-left hover:bg-[var(--card)] dark:border-[var(--border)]"
              >
                <span
                  className={`flex size-4 items-center justify-center rounded border ${
                    checked
                      ? "border-[var(--border)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "border-[var(--border)]"
                  }`}
                >
                  {checked && <Check size={10} />}
                </span>
                <span className="min-w-0 flex-1 truncate text-[11px]">
                  {row.title}
                </span>
              </button>
            );
          })
        ) : (
          <p className="py-8 text-center text-[11px] text-[var(--muted-foreground)]">
            {t("Create another reading conversation first.")}
          </p>
        )}
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="px-3 py-2 text-[11px]"
        >
          {t("Cancel")}
        </button>
        <button
          type="button"
          onClick={() => {
            setSaving(true);
            void onSave(selected).finally(() => setSaving(false));
          }}
          disabled={saving}
          className="flex h-9 items-center gap-2 rounded-xl bg-[var(--primary)] px-4 text-[11px] font-semibold text-[var(--primary-foreground)] disabled:opacity-60"
        >
          {saving && <Loader2 size={12} className="animate-spin" />}
          {t("Link conversations")}
        </button>
      </div>
    </ModalShell>
  );
}

export function NotebookCaptureDialog({
  workspaceId,
  onClose,
  onSaved,
}: {
  workspaceId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    void listNotebooks()
      .then(setNotebooks)
      .catch((caught) =>
        setError(
          caught instanceof Error
            ? caught.message
            : t("Could not load notebooks."),
        ),
      )
      .finally(() => setLoading(false));
  }, [t]);
  return (
    <ModalShell title={t("Send reading notes to Notebook")} onClose={onClose}>
      <p className="text-[11px] leading-relaxed text-[var(--muted-foreground)]">
        {t(
          "Highlights and notes are organized by source and locator before they are copied. Your material stays private in the reading workspace.",
        )}
      </p>
      <div className="mt-4 max-h-64 space-y-1 overflow-y-auto">
        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 size={15} className="animate-spin" />
          </div>
        ) : notebooks.length ? (
          notebooks.map((notebook) => {
            const checked = selected.includes(notebook.id);
            return (
              <button
                key={notebook.id}
                type="button"
                onClick={() =>
                  setSelected((current) =>
                    checked
                      ? current.filter((id) => id !== notebook.id)
                      : [...current, notebook.id],
                  )
                }
                className="flex w-full items-center gap-3 rounded-xl border border-[var(--border)] px-3 py-3 text-left hover:bg-[var(--card)] dark:border-[var(--border)]"
              >
                <span
                  className={`flex size-4 items-center justify-center rounded border ${checked ? "border-[var(--border)] bg-[var(--primary)] text-[var(--primary-foreground)]" : "border-[var(--border)]"}`}
                >
                  {checked && <Check size={10} />}
                </span>
                <NotebookPen size={13} className="text-[var(--primary)]" />
                <span className="min-w-0 flex-1 truncate text-[11px] font-medium">
                  {notebook.name}
                </span>
                <span className="text-[10px] text-[var(--muted-foreground)]">
                  {notebook.record_count ?? 0}
                </span>
              </button>
            );
          })
        ) : (
          <p className="py-8 text-center text-[11px] text-[var(--muted-foreground)]">
            {t("Create a Notebook first.")}
          </p>
        )}
      </div>
      {error && <p className="mt-3 text-[10px] text-red-600">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="px-3 py-2 text-[11px]"
        >
          {t("Cancel")}
        </button>
        <button
          type="button"
          disabled={!selected.length || saving}
          onClick={() => {
            setSaving(true);
            void sendReadingToNotebook(workspaceId, selected)
              .then(onSaved)
              .catch((caught) =>
                setError(
                  caught instanceof Error ? caught.message : t("Save failed."),
                ),
              )
              .finally(() => setSaving(false));
          }}
          className="flex h-9 items-center gap-2 rounded-xl bg-[var(--primary)] px-4 text-[11px] font-semibold text-[var(--primary-foreground)] disabled:opacity-50"
        >
          {saving && <Loader2 size={12} className="animate-spin" />}
          {t("Send to Notebook")}
        </button>
      </div>
    </ModalShell>
  );
}

export function OrganizedNotesDialog({
  notes,
  onClose,
}: {
  notes: OrganizedReadingNotes;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <ModalShell title={t("Organized reading notes")} onClose={onClose} wide>
      <div className="mb-3 flex items-center justify-between text-[10.5px] text-[var(--muted-foreground)]">
        <span>
          {t("{{count}} annotations", { count: notes.annotation_count })}
        </span>
        <button
          type="button"
          onClick={() =>
            void copyText(notes.markdown).catch(() =>
              notify(t("The clipboard is not available in this browser."), {
                tone: "error",
              }),
            )
          }
          className="flex items-center gap-1.5 rounded-lg px-2 py-1 hover:bg-[var(--muted)]"
        >
          <Copy size={11} /> {t("Copy Markdown")}
        </button>
      </div>
      <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 font-sans text-[10.5px] leading-relaxed text-[var(--muted-foreground)] dark:border-[var(--border)] dark:bg-[var(--background)] dark:text-[var(--foreground)]">
        {notes.markdown}
      </pre>
    </ModalShell>
  );
}

export function WorkspaceValueDialog({
  title,
  label,
  initialValue,
  actionLabel,
  onClose,
  onSubmit,
}: {
  title: string;
  label: string;
  initialValue: string;
  actionLabel: string;
  onClose: () => void;
  onSubmit: (value: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState(initialValue);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    if (working || !value.trim()) return;
    setWorking(true);
    setError("");
    try {
      await onSubmit(value.trim());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Save failed."));
    } finally {
      setWorking(false);
    }
  };

  return (
    <ModalShell title={title} onClose={onClose}>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className="block text-[10.5px] font-semibold uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
          {label}
          <input
            autoFocus
            value={value}
            onChange={(event) => setValue(event.target.value)}
            className="mt-2 h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 text-[12px] font-normal normal-case tracking-normal outline-none focus:border-[var(--ring)] dark:border-[var(--border)] dark:bg-[var(--background)]"
          />
        </label>
        {error && <p className="mt-3 text-[11px] text-red-600">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 text-[11px]"
          >
            {t("Cancel")}
          </button>
          <button
            type="submit"
            disabled={working || !value.trim()}
            className="flex h-9 items-center gap-2 rounded-xl bg-[var(--primary)] px-4 text-[11px] font-semibold text-[var(--primary-foreground)] disabled:opacity-60"
          >
            {working && <Loader2 size={12} className="animate-spin" />}
            {actionLabel}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

export function WorkspaceConfirmDialog({
  title,
  body,
  actionLabel,
  onClose,
  onConfirm,
}: {
  title: string;
  body: string;
  actionLabel: string;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  return (
    <ModalShell title={title} onClose={onClose}>
      <p className="text-[12px] leading-relaxed text-[var(--muted-foreground)]">
        {body}
      </p>
      {error && <p className="mt-3 text-[11px] text-red-600">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="px-3 py-2 text-[11px]"
        >
          {t("Cancel")}
        </button>
        <button
          type="button"
          disabled={working}
          onClick={() => {
            setWorking(true);
            setError("");
            void onConfirm()
              .catch((caught) =>
                setError(
                  caught instanceof Error ? caught.message : t("Save failed."),
                ),
              )
              .finally(() => setWorking(false));
          }}
          className="flex h-9 items-center gap-2 rounded-xl bg-red-700 px-4 text-[11px] font-semibold text-white disabled:opacity-60"
        >
          {working && <Loader2 size={12} className="animate-spin" />}
          {actionLabel}
        </button>
      </div>
    </ModalShell>
  );
}
