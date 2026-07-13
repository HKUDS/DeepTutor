"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  Bot,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Loader2,
  MessageSquare,
  NotebookPen,
  Pencil,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import {
  createNotebook,
  deleteNotebook,
  getNotebook,
  listNotebooks,
} from "@/lib/notebook-api";

const MarkdownRenderer = dynamic(
  () => import("@/components/common/MarkdownRenderer"),
  { ssr: false },
);

interface NotebookInfo {
  id: string;
  name: string;
  description?: string;
  record_count?: number;
  color?: string;
  icon?: string;
  updated_at?: number;
}

interface NotebookRecord {
  id: string;
  type: string;
  title: string;
  summary?: string;
  user_query?: string;
  output: string;
  metadata?: Record<string, unknown>;
  created_at?: number;
}

interface NotebookDetail extends NotebookInfo {
  records: NotebookRecord[];
}

export default function NotebooksSection() {
  const { t } = useTranslation();
  const router = useRouter();

  const [notebooks, setNotebooks] = useState<NotebookInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<NotebookDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [expandedRecordId, setExpandedRecordId] = useState<string | null>(null);

  const loadDetail = useCallback(
    async (notebookId: string, list?: NotebookInfo[]) => {
      setSelectedId(notebookId);
      setExpandedRecordId(null);
      setDetailLoading(true);
      try {
        const info = (list ?? notebooks).find((n) => n.id === notebookId);
        const data = await getNotebook(notebookId);
        const records: NotebookRecord[] = (data.records || []).map((rec) => ({
          id: String(rec.id),
          type: String(rec.type),
          title: rec.title,
          summary: rec.summary,
          user_query: rec.user_query,
          output: rec.output,
          metadata: rec.metadata,
          created_at: rec.created_at,
        }));
        setSelected({
          id: notebookId,
          name: data.name ?? info?.name ?? "",
          description: data.description ?? info?.description,
          record_count: records.length,
          color: data.color ?? info?.color,
          icon: data.icon ?? info?.icon,
          updated_at: data.updated_at ?? info?.updated_at,
          records,
        });
      } catch {
        setSelected(null);
      } finally {
        setDetailLoading(false);
      }
    },
    [notebooks],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const nbs = await listNotebooks();
      const next: NotebookInfo[] = nbs.map((nb) => ({
        id: String(nb.id),
        name: nb.name,
        description: nb.description,
        record_count: nb.record_count ?? 0,
        color: nb.color,
        icon: nb.icon,
        updated_at: nb.updated_at,
      }));
      setNotebooks(next);
      if (selectedId && next.some((n) => n.id === selectedId)) {
        void loadDetail(selectedId, next);
      } else if (!selectedId && next.length > 0) {
        void loadDetail(next[0].id, next);
      } else if (selectedId && !next.some((n) => n.id === selectedId)) {
        setSelectedId(null);
        setSelected(null);
      }
    } finally {
      setLoading(false);
    }
  }, [loadDetail, selectedId]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    await createNotebook({
      name: newName.trim(),
      description: newDescription.trim(),
    });
    setNewName("");
    setNewDescription("");
    await load();
  };

  const handleDelete = async (notebookId: string, name: string) => {
    if (!window.confirm(t('Delete notebook "{{name}}"?', { name }))) return;
    await deleteNotebook(notebookId);
    if (selectedId === notebookId) {
      setSelectedId(null);
      setSelected(null);
    }
    await load();
  };

  const openRecord = (record: NotebookRecord) => {
    const sessionId = String(record.metadata?.session_id || "");
    if (!sessionId) return;
    if (record.type === "chat") {
      router.push(`/?session=${encodeURIComponent(sessionId)}`);
    }
  };

  const formatTimestamp = (value?: number) => {
    if (!value) return t("Unknown time");
    return new Date(value * 1000).toLocaleString();
  };

  const getRecordBadge = (record: NotebookRecord) => {
    switch (record.type) {
      case "chat":
        return {
          label: t("Chat"),
          color: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
          icon: MessageSquare,
        };
      case "tutorbot": {
        // Partner conversations carry the partner's name in metadata so the
        // badge reads as that partner's own category, not a generic "Chat".
        const partnerName =
          typeof record.metadata?.partner_name === "string"
            ? record.metadata.partner_name.trim()
            : "";
        return {
          label: partnerName || t("Partner"),
          color:
            "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300",
          icon: Bot,
        };
      }
      case "research":
        return {
          label: t("Research"),
          color:
            "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
          icon: Search,
        };
      case "co_writer":
        return {
          label: t("Co-Writer"),
          color:
            "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
          icon: Pencil,
        };
      default:
        return {
          label: record.type,
          color:
            "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
          icon: NotebookPen,
        };
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <SpaceSectionHeader
        icon={NotebookPen}
        title={t("Notebooks")}
        description={t(
          "Save and organize outputs from chat, research, and Co-Writer sessions into a personal library.",
        )}
        meta={
          <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
            {notebooks.length} {t("notebooks.count.suffix")}
          </span>
        }
      />

      {/* Create notebook */}
      <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
        <div className="mb-4 flex items-center gap-2">
          <Plus size={15} className="text-[var(--muted-foreground)]" />
          <h2 className="text-[13.5px] font-semibold text-[var(--foreground)]">
            {t("Create notebook")}
          </h2>
          <span className="ml-1 text-[11.5px] text-[var(--muted-foreground)]">
            {t("Give it a name and short description.")}
          </span>
        </div>

        <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
          <input
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            placeholder={t("Notebook name")}
            className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25"
          />
          <input
            value={newDescription}
            onChange={(event) => setNewDescription(event.target.value)}
            placeholder={t("Description")}
            className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25"
          />
          <button
            onClick={() => void handleCreate()}
            disabled={!newName.trim()}
            className="rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[13px] font-medium text-[var(--primary-foreground)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t("Create")}
          </button>
        </div>
      </section>

      {/* Notebook list */}
      <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
        <div className="mb-4 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <NotebookPen size={15} className="text-[var(--muted-foreground)]" />
            <h2 className="text-[13.5px] font-semibold text-[var(--foreground)]">
              {t("Your notebooks")}
            </h2>
            <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] tabular-nums text-[var(--muted-foreground)]">
              {notebooks.length}
            </span>
          </div>
          <span className="text-[11.5px] text-[var(--muted-foreground)]">
            {t("Click a notebook to inspect its records.")}
          </span>
        </div>

        <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
          <div className="xl:sticky xl:top-8 xl:max-h-[calc(100vh-12rem)] space-y-2 overflow-y-auto pr-1">
            {notebooks.map((notebook) => {
              const active = selectedId === notebook.id;
              return (
                <div
                  key={notebook.id}
                  className={`group relative w-full rounded-xl border p-3.5 text-left transition-all ${
                    active
                      ? "border-[var(--primary)]/40 bg-[var(--primary)]/[0.08] shadow-sm"
                      : "border-[var(--border)] bg-[var(--background)] hover:border-[var(--foreground)]/20 hover:bg-[var(--muted)]/30"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => void loadDetail(notebook.id)}
                    className="block w-full text-left"
                  >
                    <div className="flex items-start gap-2.5">
                      <div
                        className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ring-2 ring-[var(--background)]"
                        style={{
                          backgroundColor: notebook.color || "var(--primary)",
                        }}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[13.5px] font-semibold text-[var(--foreground)]">
                          {notebook.name}
                        </div>
                        <p className="mt-0.5 line-clamp-1 min-h-[1.1em] text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
                          {notebook.description || (
                            <span className="italic text-[var(--muted-foreground)]/60">
                              {t("No description.")}
                            </span>
                          )}
                        </p>
                        <div className="mt-2 flex items-center justify-between gap-2 text-[10.5px] tabular-nums text-[var(--muted-foreground)]">
                          <span>
                            {notebook.record_count ?? 0} {t("records")}
                          </span>
                          <span className="truncate text-right">
                            {notebook.updated_at
                              ? formatTimestamp(notebook.updated_at)
                              : ""}
                          </span>
                        </div>
                      </div>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      void handleDelete(notebook.id, notebook.name);
                    }}
                    title={t("Delete")}
                    className="absolute right-1.5 top-1.5 rounded-md p-1.5 text-[var(--muted-foreground)] opacity-0 transition-opacity hover:bg-[var(--destructive)]/10 hover:text-[var(--destructive)] group-hover:opacity-100"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              );
            })}

            {!notebooks.length && (
              <div className="rounded-xl border border-dashed border-[var(--border)] px-6 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
                {t("No notebooks yet. Create one to organize outputs.")}
              </div>
            )}
          </div>

          <div className="flex min-h-[560px] flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--background)] p-4 xl:h-[calc(100vh-12rem)]">
            {detailLoading ? (
              <div className="flex min-h-[320px] items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
              </div>
            ) : selected ? (
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="mb-3 flex shrink-0 items-center justify-between gap-4 pb-3">
                  <div className="flex items-center gap-2.5">
                    <div
                      className="h-2.5 w-2.5 rounded-full"
                      style={{
                        backgroundColor: selected.color || "var(--primary)",
                      }}
                    />
                    <h3 className="text-[15px] font-semibold text-[var(--foreground)]">
                      {selected.name}
                    </h3>
                    {selected.description && (
                      <span className="text-[12px] text-[var(--muted-foreground)]">
                        — {selected.description}
                      </span>
                    )}
                  </div>
                  <span className="text-[11px] tabular-nums text-[var(--muted-foreground)]">
                    {selected.records?.length || 0} {t("records")}
                  </span>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                  <div className="divide-y divide-[var(--border)]">
                    {selected.records?.map((record) => {
                      const badge = getRecordBadge(record);
                      const BadgeIcon = badge.icon;
                      const expanded = expandedRecordId === record.id;
                      const canOpenSession =
                        record.type === "chat" &&
                        Boolean(record.metadata?.session_id);
                      const sessionLabel = t("Open chat session");

                      return (
                        <div key={record.id} className="group">
                          <button
                            onClick={() =>
                              setExpandedRecordId(expanded ? null : record.id)
                            }
                            className="flex w-full items-center gap-3 px-1 py-3.5 text-left transition-colors hover:bg-[var(--muted)]/30"
                          >
                            <span className="shrink-0 text-[var(--muted-foreground)]">
                              {expanded ? (
                                <ChevronDown size={14} />
                              ) : (
                                <ChevronRight size={14} />
                              )}
                            </span>
                            <span
                              className={`inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ${badge.color}`}
                            >
                              <BadgeIcon size={11} />
                              {badge.label}
                            </span>
                            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-[var(--foreground)]">
                              {record.title}
                            </span>
                            <span className="shrink-0 text-[11px] tabular-nums text-[var(--muted-foreground)]">
                              {formatTimestamp(record.created_at)}
                            </span>
                          </button>

                          {expanded && (
                            <div className="pb-4 pl-8 pr-1">
                              {record.summary && (
                                <p className="mb-3 text-[13px] leading-6 text-[var(--foreground)]/85">
                                  {record.summary}
                                </p>
                              )}
                              {record.type !== "chat" && record.user_query && (
                                <div className="mb-3 flex items-baseline gap-2 text-[12px]">
                                  <span className="shrink-0 font-medium text-[var(--muted-foreground)]">
                                    {t("Query:")}
                                  </span>
                                  <span className="text-[var(--foreground)]/70">
                                    {record.user_query}
                                  </span>
                                </div>
                              )}

                              {canOpenSession && (
                                <button
                                  onClick={() => openRecord(record)}
                                  className="mb-3 inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3.5 py-2 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--primary)]/40 hover:bg-[var(--primary)]/8 hover:text-[var(--primary)]"
                                >
                                  <ExternalLink size={13} />
                                  {sessionLabel}
                                  <ArrowRight size={13} />
                                </button>
                              )}

                              <div className="max-h-[320px] overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--muted)]/30 p-3">
                                <MarkdownRenderer
                                  content={record.output || ""}
                                  variant="prose"
                                  className="text-[12px] leading-5 text-[var(--foreground)]"
                                />
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}

                    {!selected.records?.length && (
                      <div className="px-6 py-12 text-center text-[13px] text-[var(--muted-foreground)]">
                        {t("This notebook is empty for now.")}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex min-h-[320px] items-center justify-center rounded-2xl border border-dashed border-[var(--border)] text-[13px] text-[var(--muted-foreground)]">
                {t("Select a notebook to inspect its saved records.")}
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
