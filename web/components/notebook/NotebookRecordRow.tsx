"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import {
  Bot,
  ChevronRight,
  ExternalLink,
  MessageSquare,
  NotebookPen,
  Pencil,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import NotebookRecordActions from "@/components/notebook/NotebookRecordActions";
import { notify } from "@/lib/notifications";
import type { NotebookRecordItem, NotebookSummary } from "@/lib/notebook-api";

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  { ssr: false },
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
    labelKey: "Co-Writer",
    className:
      "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
    icon: Pencil,
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
  const { t } = useTranslation();
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

  const badge = BADGES[record.type] ?? null;
  const BadgeIcon = badge?.icon ?? FALLBACK_BADGE.icon;
  const partnerName =
    typeof record.metadata?.partner_name === "string"
      ? record.metadata.partner_name.trim()
      : "";
  const badgeLabel = badge
    ? record.type === "tutorbot" && partnerName
      ? partnerName
      : t(badge.labelKey)
    : record.type;

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
      if (draftOutput !== (record.output ?? "")) changes.output = draftOutput;
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

  return (
    <div
      className={`group/row transition-opacity duration-150 ${busy ? "pointer-events-none opacity-50" : ""}`}
    >
      <div className="flex items-center gap-2.5 px-3 transition-colors duration-150 hover:bg-[var(--muted)]/40">
        <button
          type="button"
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-center gap-2.5 py-2.5 text-left focus-visible:outline-none"
          aria-expanded={expanded}
        >
          <ChevronRight
            size={13}
            className={`shrink-0 text-[var(--muted-foreground)] transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
          />
          <span
            className={`inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[10.5px] font-medium ${badge?.className ?? FALLBACK_BADGE.className}`}
          >
            <BadgeIcon size={10} />
            {badgeLabel}
          </span>
          <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-[var(--foreground)]">
            {record.title}
          </span>
        </button>

        {/* The timestamp holds its place whether or not the row is hovered —
            swapping it out for the action button made rows twitch. */}
        <span className="shrink-0 text-[11px] tabular-nums text-[var(--muted-foreground)]">
          {timestamp}
        </span>

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

      {expanded && (
        <div className="animate-pop-in px-3 pb-4 pl-9">
          {failure && (
            <p
              role="alert"
              className="mb-2.5 rounded-lg bg-[var(--destructive)]/10 px-3 py-2 text-[12px] text-[var(--destructive)]"
            >
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
              {record.summary && (
                <p className="mb-2.5 text-[12.5px] leading-6 text-[var(--foreground)]/80">
                  {record.summary}
                </p>
              )}
              {record.type !== "chat" && record.user_query && (
                <p className="mb-2.5 text-[12px] text-[var(--muted-foreground)]">
                  <span className="font-medium">{t("Query:")}</span>{" "}
                  {record.user_query}
                </p>
              )}
              {canOpenSession && (
                <button
                  type="button"
                  onClick={() => onOpenSession(sessionId)}
                  className="mb-2.5 inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11.5px] font-medium text-[var(--foreground)] transition-[background-color,border-color,color,transform] duration-150 active:scale-[0.98] hover:border-[var(--primary)]/40 hover:text-[var(--primary)]"
                >
                  <ExternalLink size={12} />
                  {t("Open chat session")}
                </button>
              )}
              <div className="max-h-[420px] overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--muted)]/25 px-3 py-2.5">
                <MarkdownRenderer
                  content={record.output || ""}
                  variant="prose"
                  className="text-[12.5px] leading-relaxed text-[var(--foreground)]"
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
  onOutputChange,
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
            { key: "write", label: t("Write"), active: !previewing },
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
          onChange={(e) => onOutputChange(e.target.value)}
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
