"use client";

import {
  ArchiveRestore,
  BookText,
  Loader2,
  MessagesSquare,
  Route,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { formatRelativeTime } from "@/lib/relative-time";
import {
  archiveCount,
  type ArchiveBuckets,
  type ArchivedConversation,
} from "@/lib/session-archive";
import {
  displaySessionTitle,
  isPlaceholderSessionTitle,
} from "@/lib/session-title";

interface ArchivedConversationsProps {
  buckets: ArchiveBuckets;
  /** Conversation being restored right now, so its row can say so. */
  restoringId?: string | null;
  onOpen: (sessionId: string) => void;
  onRestore: (sessionId: string) => void;
}

/**
 * The archive, by the surface each conversation was held in.
 *
 * Archiving is offered on every conversation row in the product, and reading
 * the flag back used to be this page's filter and nothing else — so an
 * archived study or reading conversation came back as one more line in a flat
 * list, stripped of the one thing that would let you recognise it: the topic
 * or the collection it belonged to. Three partitions and that container's name
 * on every row is the difference between a list you can scan and a pile.
 *
 * Restore is the only action here. Renaming, re-filing and deleting live on
 * the conversation row itself in the active list, and a second copy of those
 * would be a second menu to keep honest.
 */
export default function ArchivedConversations({
  buckets,
  restoringId = null,
  onOpen,
  onRestore,
}: ArchivedConversationsProps) {
  const { t, i18n } = useTranslation();
  const placeholder = t("New chat");

  if (archiveCount(buckets) === 0) {
    return (
      <p className="px-2 py-6 text-center text-[12.5px] text-[var(--muted-foreground)]">
        {t("Nothing is archived yet.")}
      </p>
    );
  }

  const renderRow = (row: ArchivedConversation) => {
    const { session } = row;
    const busy = restoringId === session.session_id;
    return (
      <div
        key={session.session_id}
        className="flex items-center justify-between gap-4 border-t border-[var(--border)]/50 py-2.5 first:border-t-0"
      >
        <button
          type="button"
          onClick={() => onOpen(session.session_id)}
          className="min-w-0 flex-1 px-1 text-left"
          title={t("Open")}
        >
          <div
            className={`truncate text-[13px] font-medium text-[var(--foreground)] ${
              isPlaceholderSessionTitle(session.title) ? "italic" : ""
            }`}
          >
            {displaySessionTitle(session.title, placeholder)}
          </div>
          <p className="mt-0.5 truncate text-[11.5px] text-[var(--muted-foreground)]">
            {[
              row.container,
              formatRelativeTime(session.updated_at, i18n.language),
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </button>
        <button
          type="button"
          onClick={() => onRestore(session.session_id)}
          disabled={busy}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-50"
        >
          {busy ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            <ArchiveRestore size={13} strokeWidth={1.8} />
          )}
          {t("Restore")}
        </button>
      </div>
    );
  };

  const renderPartition = (
    key: string,
    Icon: typeof Route,
    label: string,
    rows: ArchivedConversation[],
  ) =>
    rows.length > 0 ? (
      <div key={key} className="mt-5 first:mt-0">
        <div className="flex items-center gap-1.5 px-1 pb-1.5 text-[12px] font-medium text-[var(--muted-foreground)]">
          <Icon size={13} strokeWidth={1.8} className="shrink-0" />
          <span className="min-w-0 truncate">{label}</span>
          <span className="tabular-nums opacity-60">{rows.length}</span>
        </div>
        <div className="border-t border-[var(--border)]/60">
          {rows.map(renderRow)}
        </div>
      </div>
    ) : null;

  return (
    <div className="px-1 py-1">
      <p className="mb-4 px-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
        {t(
          "Archiving a conversation only clears it out of the sidebar — nothing is deleted. Restore one here and it goes back where it was.",
        )}
      </p>
      {renderPartition(
        "chat",
        MessagesSquare,
        t("Conversations"),
        buckets.chat,
      )}
      {renderPartition("mastery", Route, t("Mastery Path"), buckets.mastery)}
      {renderPartition(
        "reading",
        BookText,
        t("Immersive Reading"),
        buckets.reading,
      )}
    </div>
  );
}
