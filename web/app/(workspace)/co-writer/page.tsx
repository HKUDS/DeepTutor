"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { FileText, Loader2, PenLine, Plus, Trash2 } from "lucide-react";
import {
  createCoWriterDocument,
  deleteCoWriterDocument,
  listCoWriterDocuments,
  type CoWriterDocumentSummary,
} from "@/lib/co-writer-api";
import { notifyCoWriterChanged } from "@/lib/co-writer-events";
import { CO_WRITER_SAMPLE_TEMPLATE } from "./sampleTemplate";

function relativeTime(seconds: number): string {
  if (!seconds || Number.isNaN(seconds)) return "";
  const diff = Date.now() / 1000 - seconds;
  // Compact locale-neutral units; the card wraps this as "Updated {x} ago".
  if (diff < 60) return "1m";
  const mins = Math.floor(diff / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo`;
  return `${Math.floor(months / 12)}y`;
}

export default function CoWriterHomePage() {
  const router = useRouter();
  const { t } = useTranslation();
  const [documents, setDocuments] = useState<CoWriterDocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const docs = await listCoWriterDocuments();
      setDocuments(docs);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = useCallback(
    async (withTemplate: boolean) => {
      if (creating) return;
      setCreating(true);
      setError("");
      try {
        const document = await createCoWriterDocument({
          content: withTemplate ? CO_WRITER_SAMPLE_TEMPLATE : "",
        });
        notifyCoWriterChanged();
        router.push(`/co-writer/${document.id}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setCreating(false);
      }
    },
    [creating, router],
  );

  const handleDelete = useCallback(
    async (docId: string) => {
      if (deletingId) return;
      setDeletingId(docId);
      setError("");
      try {
        await deleteCoWriterDocument(docId);
        setDocuments((prev) => prev.filter((doc) => doc.id !== docId));
        setPendingDeleteId(null);
        notifyCoWriterChanged();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setDeletingId(null);
      }
    },
    [deletingId],
  );

  const renderEmpty = () => (
    <div className="flex min-h-[360px] flex-col items-center justify-center rounded-2xl border border-dashed border-[var(--border)] px-8 text-center">
      <PenLine
        size={30}
        strokeWidth={1.5}
        className="mb-3 text-[var(--muted-foreground)]"
      />
      <p className="text-[14px] font-medium text-[var(--foreground)]">
        {t("No drafts yet")}
      </p>
      <p className="mt-1.5 max-w-sm text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
        {t("Start a new markdown draft to begin writing.")}
      </p>
      <div className="mt-4 flex items-center gap-2">
        <button
          type="button"
          onClick={() => handleCreate(false)}
          disabled={creating}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {creating ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Plus size={14} />
          )}
          {t("New draft")}
        </button>
        <button
          type="button"
          onClick={() => handleCreate(true)}
          disabled={creating}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-60"
        >
          <FileText size={14} />
          {t("Start from template")}
        </button>
      </div>
    </div>
  );

  return (
    <div className="h-full overflow-y-auto bg-[var(--background)]">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <header className="mb-7 flex items-end justify-between gap-4">
          <div>
            <h1 className="text-[19px] font-semibold tracking-tight text-[var(--foreground)]">
              {t("Co-Writer")}
            </h1>
            <p className="mt-1 text-[12.5px] text-[var(--muted-foreground)]">
              {t("Manage your markdown drafts and projects.")}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => handleCreate(true)}
              disabled={creating}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-60"
            >
              <FileText size={14} />
              {t("From template")}
            </button>
            <button
              type="button"
              onClick={() => handleCreate(false)}
              disabled={creating}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12.5px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {creating ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Plus size={14} />
              )}
              {t("New draft")}
            </button>
          </div>
        </header>

        {error ? (
          <div className="mb-4 rounded-lg border border-rose-300/30 bg-rose-50/40 px-3 py-2 text-[12px] text-rose-700 dark:bg-rose-950/30 dark:text-rose-300">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-[12.5px] text-[var(--muted-foreground)]">
            <Loader2 size={16} className="animate-spin" />
            {t("Loading drafts…")}
          </div>
        ) : documents.length === 0 ? (
          renderEmpty()
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {documents.map((doc) => {
              const isPendingDelete = pendingDeleteId === doc.id;
              const isDeleting = deletingId === doc.id;
              return (
                <div
                  key={doc.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => router.push(`/co-writer/${doc.id}`)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      router.push(`/co-writer/${doc.id}`);
                    }
                  }}
                  className="group relative flex h-44 cursor-pointer flex-col rounded-2xl border border-[var(--border)] p-4 text-left transition-colors hover:border-[var(--ring)]"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-start gap-2">
                      <FileText
                        size={15}
                        className="mt-0.5 shrink-0 text-[var(--muted-foreground)]"
                      />
                      <div className="min-w-0">
                        <div
                          className="truncate text-[14px] font-medium text-[var(--foreground)]"
                          title={doc.title || t("Untitled draft")}
                        >
                          {doc.title || t("Untitled draft")}
                        </div>
                        <div className="mt-0.5 text-[11px] text-[var(--muted-foreground)]/70">
                          {t("Updated")} {relativeTime(doc.updated_at)}{" "}
                          {t("ago")}
                        </div>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        if (isPendingDelete) {
                          void handleDelete(doc.id);
                        } else {
                          setPendingDeleteId(doc.id);
                        }
                      }}
                      disabled={isDeleting}
                      title={
                        isPendingDelete
                          ? t("Click again to confirm")
                          : t("Delete draft")
                      }
                      className={`shrink-0 rounded-md p-1 transition-colors disabled:opacity-50 ${
                        isPendingDelete
                          ? "bg-rose-500/15 text-rose-600 dark:text-rose-400"
                          : "text-[var(--muted-foreground)]/60 opacity-0 hover:bg-rose-500/10 hover:text-rose-600 group-hover:opacity-100 dark:hover:text-rose-400"
                      }`}
                    >
                      {isDeleting ? (
                        <Loader2 size={13} className="animate-spin" />
                      ) : (
                        <Trash2 size={13} />
                      )}
                    </button>
                  </div>
                  <p className="mt-2.5 line-clamp-4 flex-1 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
                    {doc.preview || t("Empty draft")}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
