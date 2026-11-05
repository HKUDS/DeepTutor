"use client";

import { favoriteSnapshot, favoriteKind, FAVORITE_LABELS } from "@/lib/favorite-content";
import { favoriteRecordRoute } from "@/lib/resource-routes";
import Tooltip from "@/shared/ui/Tooltip";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import {
  BookOpen,
  FileQuestion,
  Calculator,
  Bot,
  ExternalLink,
  MessageSquare,
  NotebookPen,
  Pencil,
  Search,
  Video,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import NotebookRecordActions from "@/components/notebook/NotebookRecordActions";
import { FavoriteKindIcon } from "@/components/notebook/favorite-kinds";
import { formatRelativeTime } from "@/lib/relative-time";
import { notify } from "@/lib/notifications";
import type { NotebookRecordItem, NotebookSummary } from "@/lib/notebook-api";

const FavoriteContent = dynamic(() => import("./NotebookFavoriteContent"), {
  ssr: false,
});

const AddToNote = dynamic(
  () => import("@/features/notes/components/AddToNote"),
  { ssr: false },
);

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  {
    ssr: false,
  },
);

interface NotebookRecordRowProps {
  record: NotebookRecordItem;
  notebooks: NotebookSummary[];
  currentNotebookId: string;
  expanded: boolean;
  onToggle: () => void;
  onEdit: (
    recordId: string,
    changes: { title?: string; summary?: string; output?: string },
  ) => Promise<void>;
  onDelete: (recordId: string) => Promise<void>;
  onRelocate: (
    recordId: string,
    targetNotebookId: string,
    mode: "move" | "copy",
  ) => Promise<void>;
  onOpenSession: (sessionId: string) => void;
}

const BADGES: Record<
  string,
  { labelKey: string; className: string; icon: typeof MessageSquare }
> = {
  reading: { labelKey: "Reading", className: "bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300", icon: BookOpen },
  question: { labelKey: "Question", className: "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300", icon: FileQuestion },
  solve: { labelKey: "Solution", className: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300", icon: Calculator },
  chat: {
    labelKey: "Chat",
    className: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
    icon: MessageSquare,
  },
  tutorbot: {
    labelKey: "Partner",
    className:
      "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300",
    icon: Bot,
  },
  research: {
    labelKey: "Research",
    className:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
    icon: Search,
  },
  co_writer: {
    labelKey: "Learning notebook",
    className:
      "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
    icon: Pencil,
  },
  video_learning: {
    labelKey: "Video Learning",
    className: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
    icon: Video,
  },
};

const FALLBACK_BADGE = {
  className:
    "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  icon: NotebookPen,
};

/** Which confirmation the dialog is currently asking for, if any. */
type Pending = null | "delete" | "discard";

export default function NotebookRecordRow({
  record,
  notebooks,
  currentNotebookId,
  expanded,
  onToggle,
  onEdit,
  onDelete,
  onRelocate,
  onOpenSession,
}: NotebookRecordRowProps) {
  const { t, i18n } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending>(null);
  const [draftTitle, setDraftTitle] = useState(record.title);
  const [draftSummary, setDraftSummary] = useState(record.summary ?? "");
  const [draftOutput, setDraftOutput] = useState(record.output ?? "");
  const [failure, setFailure] = useState<string | null>(null);

  // Re-seed the draft whenever a different record lands in this row, or the
  // saved values change underneath an idle editor.
  useEffect(() => {
    if (editing) return;
    setDraftTitle(record.title);
    setDraftSummary(record.summary ?? "");
    setDraftOutput(record.output ?? "");
  }, [record.id, record.title, record.summary, record.output, editing]);

  const badge = BADGES[favoriteKind(record.type, record.metadata)] ?? null;
  const BadgeIcon = badge?.icon ?? FALLBACK_BADGE.icon;
  const partnerName =
    typeof record.metadata?.partner_name === "string"
      ? record.metadata.partner_name.trim()
      : "";
  const badgeLabel = badge
    ? record.type === "tutorbot" && partnerName
      ? partnerName
      : t(badge.labelKey)
    : t(FAVORITE_LABELS[favoriteKind(record.type, record.metadata)] || "Favorite content");

  const sessionId = String(record.metadata?.session_id ?? "");
  const canOpenSession = record.type === "chat" && Boolean(sessionId);
  const moveTargets = notebooks.filter(
    (n) => n.id !== currentNotebookId && !n.unreadable,
  );

  const dirty =
    draftTitle !== record.title ||
    draftSummary !== (record.summary ?? "") ||
    draftOutput !== (record.output ?? "");

  const startEditing = () => {
    setDraftTitle(record.title);
    setDraftSummary(record.summary ?? "");
    setDraftOutput(record.output ?? "");
    setFailure(null);
    setPreviewing(false);
    setEditing(true);
  };

  const leaveEditor = () => {
    setEditing(false);
    setFailure(null);
    setPending(null);
  };

  const requestCancel = () => {
    if (dirty) {
      setPending("discard");
      return;
    }
    leaveEditor();
  };

  const save = async () => {
    if (!draftTitle.trim()) {
      setFailure(t("A record needs a title."));
      return;
    }
    setBusy(true);
    setFailure(null);
    try {
      // Send only what actually changed — the backend treats an omitted
      // field as "leave alone", which is how a rename keeps the record's
      // other values intact.
      const changes: { title?: string; summary?: string; output?: string } = {};
      if (draftTitle !== record.title) changes.title = draftTitle.trim();
      if (draftSummary !== (record.summary ?? ""))
        changes.summary = draftSummary;
      if (Object.keys(changes).length) await onEdit(record.id, changes);
      setEditing(false);
      notify(t("Record saved"), { tone: "success" });
    } catch (err) {
      setFailure(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const runDelete = async () => {
    setBusy(true);
    setPending(null);
    try {
      await onDelete(record.id);
      notify(t("Record deleted"), { tone: "success" });
    } catch (err) {
      setFailure(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const runRelocate = async (targetId: string, mode: "move" | "copy") => {
    const target = notebooks.find((n) => n.id === targetId);
    setBusy(true);
    setFailure(null);
    try {
      await onRelocate(record.id, targetId, mode);
      notify(
        mode === "move"
          ? t('Moved to "{{name}}"', { name: target?.name ?? targetId })
          : t('Copied to "{{name}}"', { name: target?.name ?? targetId }),
        { tone: "success" },
      );
    } catch (err) {
      setFailure(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const timestamp = record.created_at
    ? new Date(record.created_at * 1000).toLocaleString()
    : "";

  const kind = favoriteKind(record.type, record.metadata);
  const messageCount = Number(record.metadata?.message_count ?? 0);

  return (
    <div
      className={`dt-fav-record${expanded ? " is-open" : ""}${busy ? " is-busy" : ""}`}
    >
      <div className="dt-fav-record-head">
        <button
          type="button"
          onClick={onToggle}
          className="dt-fav-record-toggle"
          aria-expanded={expanded}
        >
          <FavoriteKindIcon kind={kind} />
          <span className="min-w-0 flex-1">
            <span className="dt-fav-record-title">{record.title}</span>
            {!expanded && record.summary && (
              <span className="dt-fav-record-summary">{record.summary}</span>
            )}
            <span className="dt-fav-record-meta">
              <BadgeIcon size={11} aria-hidden />
              {badgeLabel}
              {messageCount > 0 && (
                <> · {t("{{count}} messages", { count: messageCount })}</>
              )}
              {record.created_at ? (
                <>
                  {" · "}
                  <time title={timestamp}>
                    {formatRelativeTime(record.created_at, i18n.language)}
                  </time>
                </>
              ) : null}
            </span>
          </span>
        </button>

        <div className="dt-fav-record-tools">
          <Tooltip label={t("Edit favorite details")} side="top">
            <button
              type="button"
              disabled={busy}
              aria-label={t("Edit favorite details")}
              onClick={() => {
                if (!expanded) onToggle();
                startEditing();
              }}
              className="dt-fav-icon-button"
            >
              <Pencil size={14} />
            </button>
          </Tooltip>
          <NotebookRecordActions
            targets={moveTargets}
            disabled={busy}
            onEdit={() => {
              if (!expanded) onToggle();
              startEditing();
            }}
            onDelete={() => setPending("delete")}
            onRelocate={(targetId, mode) => void runRelocate(targetId, mode)}
          />
        </div>
      </div>

      {expanded && (
        <div className="dt-fav-record-body animate-pop-in">
          {failure && (
            <p role="alert" className="dt-fav-record-error">
              {failure}
            </p>
          )}

          {editing ? (
            <RecordEditor
              title={draftTitle}
              summary={draftSummary}
              output={draftOutput}
              previewing={previewing}
              busy={busy}
              dirty={dirty}
              onTitleChange={setDraftTitle}
              onSummaryChange={setDraftSummary}
              onOutputChange={setDraftOutput}
              onTogglePreview={() => setPreviewing((v) => !v)}
              onSave={() => void save()}
              onCancel={requestCancel}
            />
          ) : (
            <>
              {record.summary && <p className="dt-fav-record-lead">{record.summary}</p>}
              {record.type !== "chat" && record.user_query && (
                <p className="dt-fav-record-query">
                  <span>{t("Query:")}</span> {record.user_query}
                </p>
              )}
              <div className="dt-fav-record-content">
                <FavoriteContent
                  type={record.type}
                  markdown={record.output || ""}
                  metadata={record.metadata}
                />
              </div>
              <div className="dt-fav-record-actions">
                {canOpenSession && (
                  <button
                    type="button"
                    onClick={() => onOpenSession(sessionId)}
                    className="dt-fav-button"
                  >
                    <ExternalLink size={13} />
                    {t("Open chat session")}
                  </button>
                )}
                <AddToNote
                  title={record.title}
                  markdown={record.output || ""}
                  sourceId={record.id}
                  favorite={favoriteSnapshot(
                    record,
                    notebooks.find((notebook) => notebook.id === currentNotebookId),
                  )}
                  sourceUrl={favoriteRecordRoute(currentNotebookId, record.id)}
                  className="dt-fav-add-to-note"
                />
              </div>
            </>
          )}
        </div>
      )}

      <ConfirmDialog
        open={pending === "delete"}
        title={t("Delete this record?")}
        confirmLabel={t("Delete")}
        tone="danger"
        busy={busy}
        onConfirm={() => void runDelete()}
        onCancel={() => setPending(null)}
      >
        <p className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {t('"{{title}}" will be removed from this notebook.', {
            title: record.title,
          })}
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        open={pending === "discard"}
        title={t("Discard your changes?")}
        confirmLabel={t("Discard")}
        tone="danger"
        onConfirm={leaveEditor}
        onCancel={() => setPending(null)}
      >
        <p className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {t("Your edits to this record have not been saved yet.")}
        </p>
      </ConfirmDialog>
    </div>
  );
}

/**
 * The record editor.
 *
 * Fields read as one continuous document — title, then summary, then body —
 * rather than three boxed inputs, so editing feels like working on the
 * record instead of filling a form.
 */
function RecordEditor({
  title,
  summary,
  output,
  previewing,
  busy,
  dirty,
  onTitleChange,
  onSummaryChange,
  onTogglePreview,
  onSave,
  onCancel,
}: {
  title: string;
  summary: string;
  output: string;
  previewing: boolean;
  busy: boolean;
  dirty: boolean;
  onTitleChange: (value: string) => void;
  onSummaryChange: (value: string) => void;
  onOutputChange: (value: string) => void;
  onTogglePreview: () => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]">
      <div className="flex flex-col gap-1 border-b border-[var(--border)]/70 px-3 py-2.5">
        <input
          autoFocus
          value={title}
          onChange={(e) => onTitleChange(e.target.value)}
          placeholder={t("Record title")}
          aria-label={t("Record title")}
          className="w-full border-0 bg-transparent p-0 text-[13.5px] font-semibold text-[var(--foreground)] outline-none placeholder:font-normal placeholder:text-[var(--muted-foreground)]"
        />
        <textarea
          value={summary}
          onChange={(e) => onSummaryChange(e.target.value)}
          placeholder={t("Short summary")}
          aria-label={t("Short summary")}
          rows={2}
          className="w-full resize-none border-0 bg-transparent p-0 text-[12.5px] leading-6 text-[var(--foreground)]/80 outline-none placeholder:text-[var(--muted-foreground)]"
        />
      </div>

      <p className="px-3 py-2 text-xs text-[var(--muted-foreground)]">
        {t(
          "Original content is preserved. Add it to a note to edit and organize it.",
        )}
      </p>
      <div className="flex items-center justify-between border-b border-[var(--border)]/70 bg-[var(--muted)]/25 px-3 py-1.5">
        <span className="text-[10.5px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          {t("Body")}
        </span>
        {/* A segmented switch rather than a toggling button: both states stay
            visible, so it never reads as "what am I looking at now?". */}
        <div
          role="tablist"
          aria-label={t("Body")}
          className="flex items-center gap-0.5 rounded-lg bg-[var(--muted)]/70 p-0.5"
        >
          {[
            { key: "write", label: t("Source text"), active: !previewing },
            { key: "preview", label: t("Preview"), active: previewing },
          ].map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={tab.active}
              onClick={() => {
                if (!tab.active) onTogglePreview();
              }}
              className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition-[background-color,color] duration-150 ${
                tab.active
                  ? "bg-[var(--background)] text-[var(--foreground)] shadow-sm"
                  : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {previewing ? (
        <div className="max-h-[380px] min-h-[180px] overflow-y-auto px-3 py-2.5">
          <MarkdownRenderer
            content={output || t("Nothing to preview yet.")}
            variant="prose"
            className="text-[12.5px] leading-relaxed text-[var(--foreground)]"
          />
        </div>
      ) : (
        <textarea
          value={output}
          readOnly
          rows={14}
          spellCheck={false}
          aria-label={t("Body")}
          className="max-h-[380px] min-h-[180px] w-full resize-y border-0 bg-transparent px-3 py-2.5 font-mono text-[12px] leading-relaxed text-[var(--foreground)] outline-none"
        />
      )}

      <div className="flex items-center justify-end gap-2 border-t border-[var(--border)]/70 px-3 py-2">
        {dirty && (
          <span className="mr-auto text-[11px] text-[var(--muted-foreground)]">
            {t("Unsaved changes")}
          </span>
        )}
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="rounded-lg px-2.5 py-1.5 text-[12.5px] text-[var(--muted-foreground)] transition-colors duration-150 hover:text-[var(--foreground)] disabled:opacity-40"
        >
          {t("Cancel")}
        </button>
        <button
          type="button"
          onClick={onSave}
          disabled={busy || !dirty}
          className="rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-[opacity,transform] duration-150 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {t("Save")}
        </button>
      </div>
    </div>
  );
}
