"use client";

import { useCallback, useEffect, useState, type KeyboardEvent } from "react";
import {
  AlertCircle,
  ExternalLink,
  Loader2,
  NotebookPen,
  Save,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuthStatus } from "@/hooks/useAuthStatus";
import {
  createCoWriterDocument,
  updateCoWriterDocument,
} from "@/lib/co-writer-api";
import { notifyCoWriterChanged } from "@/lib/co-writer-events";
import {
  loadChatMarkdownNoteDraft,
  EMPTY_CHAT_MARKDOWN_NOTE_DRAFT,
  reconcileChatMarkdownNoteAfterSave,
  isChatMarkdownNoteDirty,
  persistChatMarkdownNote,
  saveChatMarkdownNoteDraft,
} from "@/lib/chat-markdown-note";

const noteStore = {
  create: createCoWriterDocument,
  update: updateCoWriterDocument,
};

export default function ChatMarkdownNoteTab({
  sessionId,
}: {
  sessionId: string | null;
}) {
  const { t } = useTranslation();
  const auth = useAuthStatus();
  const ownerId =
    !auth.loading && auth.statusAvailable
      ? auth.enabled
        ? auth.userId
        : "local"
      : null;
  const draftScope = ownerId ? `${ownerId}:${sessionId ?? "pending"}` : null;
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [draft, setDraft] = useState(() => ({
    ...EMPTY_CHAT_MARKDOWN_NOTE_DRAFT,
  }));
  const { title, content, saved } = draft;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = isChatMarkdownNoteDirty({ title, content }, saved);
  const canSave = dirty && !saving;

  useEffect(() => {
    if (!ownerId || !draftScope) return;
    setDraft(loadChatMarkdownNoteDraft(ownerId, sessionId));
    setLoadedScope(draftScope);
    setError(null);
  }, [draftScope, ownerId, sessionId]);

  useEffect(() => {
    if (!ownerId || loadedScope !== draftScope) return;
    saveChatMarkdownNoteDraft(ownerId, sessionId, draft);
  }, [draft, draftScope, loadedScope, ownerId, sessionId]);

  const save = useCallback(async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const nextSaved = await persistChatMarkdownNote(
        { title, content },
        saved,
        noteStore,
      );
      setDraft((latest) => ({
        ...reconcileChatMarkdownNoteAfterSave(
          { title: latest.title, content: latest.content },
          { title, content },
          nextSaved,
        ),
        saved: nextSaved,
      }));
      notifyCoWriterChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }, [canSave, content, saved, title]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key.toLowerCase() === "s" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        void save();
      }
    },
    [save],
  );

  return (
    <form
      className="flex h-full min-h-0 flex-col"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[var(--border)]/40 bg-[var(--card)] px-3 py-2">
        <NotebookPen
          size={15}
          strokeWidth={1.8}
          className="shrink-0 text-[var(--muted-foreground)]"
        />
        <input
          type="text"
          value={title}
          onChange={(event) => {
            setDraft((latest) => ({ ...latest, title: event.target.value }));
            setError(null);
          }}
          placeholder={t("Untitled Co-Writer Document")}
          aria-label={t("Note title")}
          maxLength={200}
          className="min-w-[140px] flex-1 basis-40 rounded-md border border-transparent bg-transparent px-1 py-1 text-[13px] font-medium text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)]/60 hover:border-[var(--border)]/50 focus:border-[var(--primary)]/40 focus:bg-[var(--background)]"
        />
        {saved && !dirty ? (
          <span className="shrink-0 text-[11px] font-medium text-[var(--muted-foreground)]">
            {t("Saved")}
          </span>
        ) : null}
        {saved ? (
          <a
            href={`/co-writer/${encodeURIComponent(saved.id)}`}
            className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md border border-[var(--border)]/55 px-2 text-[11px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--primary)]/35 hover:text-[var(--primary)]"
          >
            <ExternalLink size={11} strokeWidth={1.9} />
            {t("Open in Co-Writer")}
          </a>
        ) : null}
        <button
          type="submit"
          disabled={!canSave}
          className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md bg-[var(--primary)] px-2.5 text-[11px] font-semibold text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {saving ? (
            <Loader2 size={11} className="animate-spin" />
          ) : (
            <Save size={11} strokeWidth={1.9} />
          )}
          {t("Save")}
        </button>
      </div>
      {error ? (
        <div
          role="alert"
          className="flex shrink-0 items-start gap-2 border-b border-[var(--border)]/30 bg-[var(--destructive)]/8 px-3 py-2 text-[11px] leading-snug text-[var(--destructive)]"
        >
          <AlertCircle
            size={12}
            strokeWidth={1.9}
            className="mt-[1px] shrink-0"
          />
          <span>
            {t("Save failed")}
            {error ? `: ${error}` : ""}
          </span>
        </div>
      ) : null}
      <textarea
        value={content}
        onChange={(event) => {
          setDraft((latest) => ({ ...latest, content: event.target.value }));
          setError(null);
        }}
        onKeyDown={handleKeyDown}
        placeholder={t("Start writing in Markdown...")}
        aria-label={t("Markdown")}
        className="min-h-0 flex-1 resize-none bg-[var(--card)] px-3 py-3 font-mono text-[12.5px] leading-relaxed text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]/60"
      />
    </form>
  );
}
