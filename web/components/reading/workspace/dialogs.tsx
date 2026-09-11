"use client";

import {
  Check,
  Copy,
  Loader2,
  NotebookPen,
  PenLine,
  Plus,
  Send,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { SessionAvatar } from "@/components/sidebar/SessionAvatar";
import { type NotebookSummary, listNotebooks } from "@/lib/notebook-api";
import { formatRelativeTime } from "@/lib/relative-time";
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

function ConversationRowAction({
  icon: Icon,
  label,
  onClick,
  danger = false,
}: {
  icon: typeof PenLine;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className={`flex size-6 items-center justify-center rounded-lg transition-[background-color,color,transform] duration-150 active:scale-90 hover:bg-[var(--background)] ${
        danger
          ? "text-[var(--muted-foreground)] hover:text-[var(--destructive)]"
          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      }`}
    >
      <Icon size={11} />
    </button>
  );
}

export function ConversationMenu({
  conversations,
  activeSessionId,
  onSelect,
  onNew,
  onRename,
  onDelete,
}: {
  conversations: ReadingConversation[];
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  /** Rename this conversation. The backend has always allowed it. */
  onRename: (conversation: ReadingConversation) => void;
  /** Delete this conversation, after the caller confirms. */
  onDelete: (conversation: ReadingConversation) => void;
}) {
  const { t, i18n } = useTranslation();
  const renameLabel = t("Rename");
  const deleteLabel = t("Delete");
  return (
    <div className="absolute right-2 top-10 z-50 w-72 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-2.5 shadow-[0_20px_50px_rgba(0,0,0,.18)] dark:border-[var(--border)] dark:bg-[var(--popover)]">
      <div className="mb-1.5 flex items-center justify-between px-1.5 py-1">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--muted-foreground)]">
          {t("Reading conversations")}
        </p>
        <button
          type="button"
          onClick={onNew}
          className="flex items-center gap-1 rounded-lg px-2 py-1 text-[10px] font-semibold text-[var(--primary)] transition hover:bg-[color-mix(in_srgb,var(--primary)_10%,transparent)]"
        >
          <Plus size={10} /> {t("New")}
        </button>
      </div>
      <div className="max-h-64 space-y-0.5 overflow-y-auto">
        {conversations.map((row) => {
          const active = row.session_id === activeSessionId;
          return (
            <div
              key={row.session_id}
              className={`group/row relative flex w-full items-center gap-1 overflow-hidden rounded-xl transition-colors ${
                active ? "bg-[color-mix(in_srgb,var(--primary)_10%,transparent)]" : "hover:bg-[var(--muted)]"
              }`}
            >
              {active && (
                <span className="absolute left-0 top-1/2 h-4 w-[2.5px] -translate-y-1/2 rounded-r-full bg-[var(--primary)]" />
              )}
              <button
                type="button"
                onClick={() => onSelect(row.session_id)}
                className="flex min-w-0 flex-1 items-center gap-2.5 py-2.5 pl-3 pr-1.5 text-left"
              >
                <SessionAvatar sessionId={row.session_id} size={13} />
                <div className="min-w-0 flex-1">
                  <p
                    className={`truncate text-[11px] ${active ? "font-semibold text-[var(--foreground)]" : "font-medium text-[var(--foreground)]"}`}
                  >
                    {row.title}
                  </p>
                  <p className="mt-0.5 text-[9.5px] text-[var(--muted-foreground)]">
                    {formatRelativeTime(row.updated_at, i18n.language)}
                  </p>
                </div>
                {active && (
                  <Check size={11} className="shrink-0 text-[var(--primary)]" />
                )}
              </button>
              {/* Revealed on hover so a list of conversations still reads as a
                  list. Keyboard users reach them by tabbing, which is why they
                  are always in the DOM rather than conditionally rendered. */}
              <span className="flex shrink-0 items-center pr-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover/row:opacity-100">
                <ConversationRowAction
                  icon={PenLine}
                  label={renameLabel}
                  onClick={() => onRename(row)}
                />
                <ConversationRowAction
                  icon={Trash2}
                  label={deleteLabel}
                  danger
                  onClick={() => onDelete(row)}
                />
              </span>
            </div>
          );
        })}
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
