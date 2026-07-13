"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  ChevronUp,
  ClipboardList,
  Database,
  Loader2,
  MessagesSquare,
  NotebookPen,
  Pencil,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppShell } from "@/context/AppShellContext";
import type { BookProposal } from "@/lib/book-types";
import {
  listKnowledgeBases,
  type KnowledgeBaseSummary,
} from "@/lib/knowledge-api";
import {
  getNotebook,
  listCategories,
  listNotebookEntries,
  listNotebooks,
  type NotebookCategory,
  type NotebookEntry,
  type NotebookRecordItem,
  type NotebookSummary,
} from "@/lib/notebook-api";
import {
  getSession,
  listSessions,
  type SessionMessage,
  type SessionSummary,
} from "@/lib/session-api";

type SourceTab = "knowledge" | "notebooks" | "questions" | "chats";

type Translate = (key: string, options?: Record<string, unknown>) => string;

type ParentSelection<TChild extends string | number> =
  | { mode: "all" }
  | { mode: "subset"; ids: Set<TChild> };

type ParentMap<
  TParent extends string | number,
  TChild extends string | number,
> = Map<TParent, ParentSelection<TChild>>;

export interface BookCreatorProps {
  onCreate: (payload: {
    user_intent: string;
    chat_session_id: string;
    chat_selections: Array<{ session_id: string; message_ids: number[] }>;
    knowledge_bases: string[];
    notebook_refs: Array<Record<string, unknown>>;
    question_categories: number[];
    question_entries: number[];
    language: string;
  }) => void | Promise<void>;
  loading?: boolean;
  proposal?: BookProposal | null;
  onConfirmProposal?: (edited: BookProposal) => void | Promise<void>;
  confirmLoading?: boolean;
}

export default function BookCreator({
  onCreate,
  loading = false,
  proposal = null,
  onConfirmProposal,
  confirmLoading = false,
}: BookCreatorProps) {
  const { t } = useTranslation();
  const { language: appLanguage } = useAppShell();
  const [intent, setIntent] = useState("");
  const [language, setLanguage] = useState(appLanguage);
  const languageTouchedRef = useRef(false);
  const [tab, setTab] = useState<SourceTab>("knowledge");

  // Knowledge bases (flat selection)
  const [kbs, setKbs] = useState<KnowledgeBaseSummary[]>([]);
  const [kbsLoading, setKbsLoading] = useState(false);
  const [selectedKbs, setSelectedKbs] = useState<Set<string>>(new Set());

  // Notebooks → records (tree selection)
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [notebooksLoading, setNotebooksLoading] = useState(false);
  const [notebookSelection, setNotebookSelection] = useState<
    ParentMap<string, string>
  >(new Map());
  const [notebookExpanded, setNotebookExpanded] = useState<Set<string>>(
    new Set(),
  );
  const [notebookRecords, setNotebookRecords] = useState<
    Record<string, NotebookRecordItem[]>
  >({});
  const [notebookRecordsLoading, setNotebookRecordsLoading] = useState<
    Record<string, boolean>
  >({});

  // Question bank: categories → entries
  const [categories, setCategories] = useState<NotebookCategory[]>([]);
  const [categoriesLoading, setCategoriesLoading] = useState(false);
  const [questionSelection, setQuestionSelection] = useState<
    ParentMap<number, number>
  >(new Map());
  const [questionExpanded, setQuestionExpanded] = useState<Set<number>>(
    new Set(),
  );
  const [questionEntries, setQuestionEntries] = useState<
    Record<number, NotebookEntry[]>
  >({});
  const [questionEntriesLoading, setQuestionEntriesLoading] = useState<
    Record<number, boolean>
  >({});

  // Chat history: sessions → messages
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [chatSelection, setChatSelection] = useState<ParentMap<string, number>>(
    new Map(),
  );
  const [chatExpanded, setChatExpanded] = useState<Set<string>>(new Set());
  const [chatMessages, setChatMessages] = useState<
    Record<string, SessionMessage[]>
  >({});
  const [chatMessagesLoading, setChatMessagesLoading] = useState<
    Record<string, boolean>
  >({});

  const [editProposal, setEditProposal] = useState<BookProposal | null>(null);
  const [formCollapsed, setFormCollapsed] = useState(false);
  const lastSeenProposalIdRef = useRef<string | null>(null);

  // Auto-collapse the form once the proposal first arrives (never overwrites
  // a manual expand later because we only fire on identity change).
  useEffect(() => {
    const id = proposal ? proposal.title || "_proposal_" : null;
    if (id && id !== lastSeenProposalIdRef.current) {
      setFormCollapsed(true);
    }
    lastSeenProposalIdRef.current = id;
  }, [proposal]);

  const refreshKbs = async () => {
    setKbsLoading(true);
    try {
      setKbs(await listKnowledgeBases({ force: true }));
    } catch {
      setKbs([]);
    } finally {
      setKbsLoading(false);
    }
  };
  const refreshNotebooks = async () => {
    setNotebooksLoading(true);
    try {
      setNotebooks(await listNotebooks());
    } catch {
      setNotebooks([]);
    } finally {
      setNotebooksLoading(false);
    }
  };
  const refreshCategories = async () => {
    setCategoriesLoading(true);
    try {
      setCategories(await listCategories());
    } catch {
      setCategories([]);
    } finally {
      setCategoriesLoading(false);
    }
  };
  const refreshSessions = async () => {
    setSessionsLoading(true);
    try {
      setSessions(await listSessions(50, 0, { force: true }));
    } catch {
      setSessions([]);
    } finally {
      setSessionsLoading(false);
    }
  };

  useEffect(() => {
    void refreshKbs();
    void refreshNotebooks();
    void refreshCategories();
    void refreshSessions();
  }, []);

  useEffect(() => {
    if (!languageTouchedRef.current) setLanguage(appLanguage);
  }, [appLanguage]);

  // ── selection counts ─────────────────────────────────────────────
  const countSelection = <P extends string | number, C extends string | number>(
    map: ParentMap<P, C>,
  ): number => {
    let n = 0;
    map.forEach((sel) => {
      n += sel.mode === "all" ? 1 : sel.ids.size;
    });
    return n;
  };
  const nbCount = countSelection(notebookSelection);
  const qCount = countSelection(questionSelection);
  const chatCount = countSelection(chatSelection);
  const totalSelected = selectedKbs.size + nbCount + qCount + chatCount;

  // ── generic tree-selection helpers ───────────────────────────────
  const toggleParent = <P extends string | number, C extends string | number>(
    map: ParentMap<P, C>,
    parent: P,
  ): ParentMap<P, C> => {
    const next = new Map(map);
    if (next.has(parent)) next.delete(parent);
    else next.set(parent, { mode: "all" });
    return next;
  };
  const toggleChild = <P extends string | number, C extends string | number>(
    map: ParentMap<P, C>,
    parent: P,
    child: C,
    knownChildren: C[],
  ): ParentMap<P, C> => {
    const next = new Map(map);
    const current = next.get(parent);
    let ids: Set<C>;
    if (!current) {
      ids = new Set([child]);
    } else if (current.mode === "all") {
      // materialize: all known children except the one being unchecked
      ids = new Set(knownChildren.filter((c) => c !== child));
    } else {
      ids = new Set(current.ids);
      if (ids.has(child)) ids.delete(child);
      else ids.add(child);
    }
    if (ids.size === 0) next.delete(parent);
    else next.set(parent, { mode: "subset", ids });
    return next;
  };

  const toggleKb = (name: string) => {
    setSelectedKbs((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  // ── lazy children loaders ────────────────────────────────────────
  const ensureNotebookRecords = async (id: string) => {
    if (notebookRecords[id] || notebookRecordsLoading[id]) return;
    setNotebookRecordsLoading((p) => ({ ...p, [id]: true }));
    try {
      const detail = await getNotebook(id);
      setNotebookRecords((p) => ({ ...p, [id]: detail.records ?? [] }));
    } catch {
      setNotebookRecords((p) => ({ ...p, [id]: [] }));
    } finally {
      setNotebookRecordsLoading((p) => ({ ...p, [id]: false }));
    }
  };
  const ensureQuestionEntries = async (id: number) => {
    if (questionEntries[id] || questionEntriesLoading[id]) return;
    setQuestionEntriesLoading((p) => ({ ...p, [id]: true }));
    try {
      const result = await listNotebookEntries({ category_id: id, limit: 200 });
      setQuestionEntries((p) => ({ ...p, [id]: result.items }));
    } catch {
      setQuestionEntries((p) => ({ ...p, [id]: [] }));
    } finally {
      setQuestionEntriesLoading((p) => ({ ...p, [id]: false }));
    }
  };
  const ensureChatMessages = async (sid: string) => {
    if (chatMessages[sid] || chatMessagesLoading[sid]) return;
    setChatMessagesLoading((p) => ({ ...p, [sid]: true }));
    try {
      const detail = await getSession(sid);
      setChatMessages((p) => ({ ...p, [sid]: detail.messages ?? [] }));
    } catch {
      setChatMessages((p) => ({ ...p, [sid]: [] }));
    } finally {
      setChatMessagesLoading((p) => ({ ...p, [sid]: false }));
    }
  };

  // ── submit ───────────────────────────────────────────────────────
  const handleCreate = async () => {
    if (!intent.trim()) return;

    const notebook_refs: Array<{ notebook_id: string; record_ids: string[] }> =
      [];
    notebookSelection.forEach((sel, id) => {
      notebook_refs.push({
        notebook_id: id,
        record_ids: sel.mode === "all" ? [] : Array.from(sel.ids),
      });
    });

    const question_categories: number[] = [];
    const question_entries: number[] = [];
    questionSelection.forEach((sel, id) => {
      if (sel.mode === "all") question_categories.push(id);
      else sel.ids.forEach((eid) => question_entries.push(eid));
    });

    const chat_selections: Array<{
      session_id: string;
      message_ids: number[];
    }> = [];
    chatSelection.forEach((sel, sid) => {
      chat_selections.push({
        session_id: sid,
        message_ids: sel.mode === "all" ? [] : Array.from(sel.ids),
      });
    });

    await onCreate({
      user_intent: intent,
      chat_session_id: "",
      chat_selections,
      knowledge_bases: Array.from(selectedKbs),
      notebook_refs,
      question_categories,
      question_entries,
      language,
    });
  };

  const currentProposal = editProposal || proposal;

  const tabConfig: Array<{
    key: SourceTab;
    label: string;
    icon: typeof Database;
    count: number;
  }> = [
    {
      key: "knowledge",
      label: t("KB"),
      icon: Database,
      count: selectedKbs.size,
    },
    {
      key: "notebooks",
      label: t("Notebooks"),
      icon: NotebookPen,
      count: nbCount,
    },
    {
      key: "questions",
      label: t("Questions"),
      icon: ClipboardList,
      count: qCount,
    },
    { key: "chats", label: t("Chats"), icon: MessagesSquare, count: chatCount },
  ];

  // Summary chips shown in the collapsed form header so users always see what
  // sources their proposal was generated from (even after collapsing).
  const summaryChips: Array<{ icon: typeof Database; label: string }> = [];
  if (selectedKbs.size > 0) {
    summaryChips.push({
      icon: Database,
      label: t("{{count}} KB", { count: selectedKbs.size }),
    });
  }
  if (nbCount > 0) {
    summaryChips.push({
      icon: NotebookPen,
      label: t(
        nbCount === 1
          ? "{{count}} notebook record"
          : "{{count}} notebook records",
        { count: nbCount },
      ),
    });
  }
  if (qCount > 0) {
    summaryChips.push({
      icon: ClipboardList,
      label: t(qCount === 1 ? "{{count}} quiz item" : "{{count}} quiz items", {
        count: qCount,
      }),
    });
  }
  if (chatCount > 0) {
    summaryChips.push({
      icon: MessagesSquare,
      label: t(
        chatCount === 1 ? "{{count}} chat item" : "{{count}} chat items",
        { count: chatCount },
      ),
    });
  }

  return (
    <div className="mx-auto w-full max-w-2xl space-y-5 p-6">
      <div className="space-y-1.5">
        <h1 className="font-serif text-2xl font-semibold text-[var(--foreground)]">
          {t("Create a new book")}
        </h1>
        <p className="text-sm text-[var(--muted-foreground)]">
          {t(
            "Describe what you want to learn, then pick the knowledge sources to fuse into a structured, interactive book.",
          )}
        </p>
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
        <button
          type="button"
          onClick={() => setFormCollapsed((v) => !v)}
          className="flex w-full items-center justify-between gap-3 rounded-t-2xl px-5 py-3 text-left hover:bg-[var(--muted)]/40"
        >
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-[var(--foreground)]">
                {formCollapsed ? t("Inputs") : t("Configure inputs")}
              </span>
              {formCollapsed && intent.trim() && (
                <span className="truncate text-xs text-[var(--muted-foreground)]">
                  · {clip(intent, 90)}
                </span>
              )}
            </div>
            {formCollapsed && (
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                {summaryChips.length === 0 ? (
                  <span className="text-[11px] text-[var(--muted-foreground)]">
                    {t("No knowledge sources selected")}
                  </span>
                ) : (
                  summaryChips.map((chip, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 rounded-full bg-[var(--primary)]/10 px-2 py-0.5 text-[11px] font-medium text-[var(--primary)]"
                    >
                      <chip.icon className="h-3 w-3" />
                      {chip.label}
                    </span>
                  ))
                )}
              </div>
            )}
          </div>
          <span className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-[var(--muted-foreground)]">
            {formCollapsed ? (
              <>
                <Pencil className="h-3 w-3" />
                {t("Edit")}
              </>
            ) : (
              <ChevronUp className="h-3.5 w-3.5" />
            )}
          </span>
        </button>

        {!formCollapsed && (
          <div className="space-y-4 px-5 pb-5">
            <label className="block">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
                {t("Learning intent")}
              </span>
              <textarea
                value={intent}
                onChange={(e) => setIntent(e.target.value)}
                rows={5}
                placeholder={t(
                  "e.g. Build intuition for transformer attention with derivations and exercises.",
                )}
                className="mt-1.5 w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] outline-none focus:border-[var(--primary)]/50"
              />
            </label>

            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
                  {t("Knowledge sources")}
                  {totalSelected > 0 && (
                    <span className="ml-2 rounded-full bg-[var(--primary)]/15 px-2 py-0.5 text-[10px] font-semibold text-[var(--primary)]">
                      {t("{{count}} selected", { count: totalSelected })}
                    </span>
                  )}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    if (tab === "knowledge") void refreshKbs();
                    else if (tab === "notebooks") void refreshNotebooks();
                    else if (tab === "questions") void refreshCategories();
                    else void refreshSessions();
                  }}
                  className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                >
                  <RefreshCw className="h-3 w-3" />
                  {t("Refresh")}
                </button>
              </div>

              <div className="inline-flex w-full rounded-lg border border-[var(--border)] bg-[var(--muted)] p-0.5">
                {tabConfig.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => setTab(item.key)}
                    className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-[12px] font-medium transition-all ${
                      tab === item.key
                        ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                        : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    <item.icon size={13} />
                    {item.label}
                    {item.count > 0 && (
                      <span
                        className={`ml-0.5 rounded-full px-1.5 text-[10px] font-semibold ${
                          tab === item.key
                            ? "bg-[var(--primary)]/15 text-[var(--primary)]"
                            : "bg-[var(--border)]/70 text-[var(--muted-foreground)]"
                        }`}
                      >
                        {item.count}
                      </span>
                    )}
                  </button>
                ))}
              </div>

              <div className="max-h-72 overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--background)] p-1.5">
                {tab === "knowledge" && (
                  <FlatList
                    loading={kbsLoading}
                    emptyHint={t(
                      "No knowledge bases yet. Create one in the Knowledge page first.",
                    )}
                    items={kbs.map((kb) => ({
                      key: kb.name,
                      primary: kb.name,
                      secondary: kb.is_default ? t("default") : kb.status || "",
                      checked: selectedKbs.has(kb.name),
                      onToggle: () => toggleKb(kb.name),
                    }))}
                  />
                )}

                {tab === "notebooks" && (
                  <TreeList
                    loading={notebooksLoading}
                    emptyHint={t(
                      "No notebooks yet. Save chat outputs into a notebook first.",
                    )}
                    parents={notebooks.map((nb) => {
                      const records = notebookRecords[nb.id];
                      return {
                        id: nb.id,
                        title: nb.name,
                        subtitle: parentSubtitle(
                          notebookSelection.get(nb.id),
                          records?.length ?? nb.record_count ?? 0,
                          t("record"),
                          t("records"),
                          t,
                        ),
                        expanded: notebookExpanded.has(nb.id),
                        childrenLoading: !!notebookRecordsLoading[nb.id],
                        children: (records ?? []).map((rec) => ({
                          id: rec.id,
                          title: rec.title || t("(untitled)"),
                          subtitle: rec.summary || "",
                        })),
                        selection: notebookSelection.get(nb.id),
                      };
                    })}
                    onToggleParent={(id) =>
                      setNotebookSelection((prev) => toggleParent(prev, id))
                    }
                    onToggleChild={(parentId, childId, knownChildren) =>
                      setNotebookSelection((prev) =>
                        toggleChild(prev, parentId, childId, knownChildren),
                      )
                    }
                    onToggleExpand={(id) => {
                      setNotebookExpanded((prev) => {
                        const next = new Set(prev);
                        if (next.has(id)) next.delete(id);
                        else {
                          next.add(id);
                          void ensureNotebookRecords(id);
                        }
                        return next;
                      });
                    }}
                  />
                )}

                {tab === "questions" && (
                  <TreeList<number, number>
                    loading={categoriesLoading}
                    emptyHint={t(
                      "No quiz categories yet. Bookmark questions into a category first.",
                    )}
                    parents={categories.map((cat) => {
                      const entries = questionEntries[cat.id];
                      return {
                        id: cat.id,
                        title: cat.name,
                        subtitle: parentSubtitle(
                          questionSelection.get(cat.id),
                          entries?.length ?? cat.entry_count ?? 0,
                          t("entry"),
                          t("entries"),
                          t,
                        ),
                        expanded: questionExpanded.has(cat.id),
                        childrenLoading: !!questionEntriesLoading[cat.id],
                        children: (entries ?? []).map((e) => ({
                          id: e.id,
                          title: e.question || t("(no question)"),
                          subtitle: `${e.is_correct ? "✓" : "✗"} ${
                            e.user_answer
                              ? t("your: {{answer}}", { answer: e.user_answer })
                              : t("no attempt")
                          } · ${t("correct: {{answer}}", {
                            answer: e.correct_answer,
                          })}`,
                        })),
                        selection: questionSelection.get(cat.id),
                      };
                    })}
                    onToggleParent={(id) =>
                      setQuestionSelection((prev) => toggleParent(prev, id))
                    }
                    onToggleChild={(parentId, childId, knownChildren) =>
                      setQuestionSelection((prev) =>
                        toggleChild(prev, parentId, childId, knownChildren),
                      )
                    }
                    onToggleExpand={(id) => {
                      setQuestionExpanded((prev) => {
                        const next = new Set(prev);
                        if (next.has(id)) next.delete(id);
                        else {
                          next.add(id);
                          void ensureQuestionEntries(id);
                        }
                        return next;
                      });
                    }}
                  />
                )}

                {tab === "chats" && (
                  <TreeList<string, number>
                    loading={sessionsLoading}
                    emptyHint={t("No chat sessions yet.")}
                    parents={sessions.map((s) => {
                      const msgs = chatMessages[s.session_id];
                      return {
                        id: s.session_id,
                        title: s.title || t("(untitled chat)"),
                        subtitle: parentSubtitle(
                          chatSelection.get(s.session_id),
                          msgs?.length ?? s.message_count ?? 0,
                          t("message"),
                          t("messages"),
                          t,
                        ),
                        expanded: chatExpanded.has(s.session_id),
                        childrenLoading: !!chatMessagesLoading[s.session_id],
                        children: (msgs ?? []).map((m) => ({
                          id: m.id,
                          title: `${m.role}${m.capability ? ` · ${m.capability}` : ""}`,
                          subtitle: clip(m.content, 140),
                        })),
                        selection: chatSelection.get(s.session_id),
                      };
                    })}
                    onToggleParent={(id) =>
                      setChatSelection((prev) => toggleParent(prev, id))
                    }
                    onToggleChild={(parentId, childId, knownChildren) =>
                      setChatSelection((prev) =>
                        toggleChild(prev, parentId, childId, knownChildren),
                      )
                    }
                    onToggleExpand={(id) => {
                      setChatExpanded((prev) => {
                        const next = new Set(prev);
                        if (next.has(id)) next.delete(id);
                        else {
                          next.add(id);
                          void ensureChatMessages(id);
                        }
                        return next;
                      });
                    }}
                  />
                )}
              </div>
            </div>

            <div className="flex items-center justify-between gap-3">
              <label className="text-xs text-[var(--muted-foreground)]">
                {t("Language")}{" "}
                <select
                  value={language}
                  onChange={(e) => {
                    languageTouchedRef.current = true;
                    setLanguage(e.target.value as "en" | "zh");
                  }}
                  className="ml-1 rounded-md border border-[var(--border)] bg-[var(--background)] px-1.5 py-0.5 text-xs text-[var(--foreground)]"
                >
                  <option value="en">{t("language.english")}</option>
                  <option value="zh">{t("language.chinese")}</option>
                </select>
              </label>
              <button
                onClick={handleCreate}
                disabled={loading || !intent.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                {t("Generate proposal")}
              </button>
            </div>
          </div>
        )}
      </div>

      {currentProposal && onConfirmProposal && (
        <div className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
          <div>
            <h2 className="text-base font-semibold text-[var(--foreground)]">
              {t("Proposal")}
            </h2>
            <p className="text-xs text-[var(--muted-foreground)]">
              {t(
                "Edit anything below, then confirm to generate the chapter spine.",
              )}
            </p>
          </div>
          <ProposalForm
            proposal={currentProposal}
            onChange={setEditProposal}
            selectedKbs={Array.from(selectedKbs)}
          />
          <div className="flex justify-end">
            <button
              onClick={() =>
                editProposal
                  ? onConfirmProposal(editProposal)
                  : onConfirmProposal(currentProposal)
              }
              disabled={confirmLoading}
              className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
            >
              {confirmLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              {t("Confirm proposal & build spine")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── helpers ───────────────────────────────────────────────────────────

function clip(text: string, n: number): string {
  if (!text) return "";
  const t = text.replace(/\s+/g, " ").trim();
  return t.length <= n ? t : t.slice(0, n) + "…";
}

function parentSubtitle<C extends string | number>(
  sel: ParentSelection<C> | undefined,
  total: number,
  unit: string,
  unitPlural?: string,
  t?: Translate,
): string {
  const plural = unitPlural || `${unit}s`;
  const fmt = (n: number) => `${n} ${n === 1 ? unit : plural}`;
  if (!sel) return total > 0 ? fmt(total) : `0 ${plural}`;
  if (sel.mode === "all") {
    return total > 0
      ? `${t ? t("All") : "All"} ${fmt(total)}`
      : t
        ? t("All")
        : "All";
  }
  return total > 0
    ? t
      ? t("{{selected}} of {{total}}", {
          selected: sel.ids.size,
          total: fmt(total),
        })
      : `${sel.ids.size} of ${fmt(total)}`
    : t
      ? t("{{count}} selected", { count: sel.ids.size })
      : `${sel.ids.size} selected`;
}

// ─── checkbox icon ─────────────────────────────────────────────────────

function CheckBox({ state }: { state: "off" | "on" | "indeterminate" }) {
  if (state === "off") {
    return (
      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-[var(--border)] bg-[var(--background)]" />
    );
  }
  if (state === "indeterminate") {
    return (
      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-[var(--primary)] bg-[var(--primary)]">
        <span className="h-[2px] w-2 rounded bg-[var(--primary-foreground)]" />
      </span>
    );
  }
  return (
    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]">
      <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
        <path
          d="M2.5 6.5L5 9L9.5 3.5"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

// ─── flat list (for KB tab) ────────────────────────────────────────────

function FlatList({
  loading,
  emptyHint,
  items,
}: {
  loading: boolean;
  emptyHint: string;
  items: Array<{
    key: string;
    primary: string;
    secondary?: string;
    checked: boolean;
    onToggle: () => void;
  }>;
}) {
  const { t } = useTranslation();
  if (loading)
    return (
      <div className="flex items-center justify-center gap-2 py-6 text-xs text-[var(--muted-foreground)]">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t("Loading…")}
      </div>
    );
  if (items.length === 0)
    return (
      <div className="flex items-center justify-center px-3 py-6 text-center text-xs text-[var(--muted-foreground)]">
        {emptyHint}
      </div>
    );
  return (
    <ul className="space-y-0.5">
      {items.map((item) => (
        <li key={item.key}>
          <button
            type="button"
            onClick={item.onToggle}
            className={`flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors ${
              item.checked
                ? "bg-[var(--primary)]/10"
                : "hover:bg-[var(--muted)]/60"
            }`}
          >
            <CheckBox state={item.checked ? "on" : "off"} />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium text-[var(--foreground)]">
                {item.primary}
              </div>
              {item.secondary && (
                <div className="truncate text-[11px] text-[var(--muted-foreground)]">
                  {item.secondary}
                </div>
              )}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

// ─── tree list (for notebooks / questions / chats) ─────────────────────

interface TreeChild<C extends string | number> {
  id: C;
  title: string;
  subtitle?: string;
}

interface TreeParent<P extends string | number, C extends string | number> {
  id: P;
  title: string;
  subtitle?: string;
  expanded: boolean;
  childrenLoading: boolean;
  children: TreeChild<C>[];
  selection: ParentSelection<C> | undefined;
}

function TreeList<
  P extends string | number = string,
  C extends string | number = string,
>({
  loading,
  emptyHint,
  parents,
  onToggleParent,
  onToggleChild,
  onToggleExpand,
}: {
  loading: boolean;
  emptyHint: string;
  parents: TreeParent<P, C>[];
  onToggleParent: (id: P) => void;
  onToggleChild: (parentId: P, childId: C, knownChildren: C[]) => void;
  onToggleExpand: (id: P) => void;
}) {
  const { t } = useTranslation();
  if (loading)
    return (
      <div className="flex items-center justify-center gap-2 py-6 text-xs text-[var(--muted-foreground)]">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t("Loading…")}
      </div>
    );
  if (parents.length === 0)
    return (
      <div className="flex items-center justify-center px-3 py-6 text-center text-xs text-[var(--muted-foreground)]">
        {emptyHint}
      </div>
    );

  return (
    <ul className="space-y-0.5">
      {parents.map((p) => {
        const sel = p.selection;
        const parentState: "on" | "off" | "indeterminate" = !sel
          ? "off"
          : sel.mode === "all"
            ? "on"
            : "indeterminate";

        return (
          <li key={String(p.id)}>
            <div
              className={`group flex items-center gap-1 rounded-md pr-2 transition-colors ${
                sel ? "bg-[var(--primary)]/8" : "hover:bg-[var(--muted)]/60"
              }`}
            >
              <button
                type="button"
                onClick={() => onToggleExpand(p.id)}
                className="flex h-7 w-6 shrink-0 items-center justify-center text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                aria-label={p.expanded ? t("Collapse") : t("Expand")}
              >
                {p.expanded ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
              </button>
              <button
                type="button"
                onClick={() => onToggleParent(p.id)}
                className="flex min-w-0 flex-1 items-center gap-2.5 py-1.5 text-left text-[13px]"
              >
                <CheckBox state={parentState} />
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium text-[var(--foreground)]">
                    {p.title}
                  </div>
                  {p.subtitle && (
                    <div className="truncate text-[11px] text-[var(--muted-foreground)]">
                      {p.subtitle}
                    </div>
                  )}
                </div>
              </button>
            </div>

            {p.expanded && (
              <div className="ml-6 mt-0.5 border-l border-[var(--border)] pl-1.5">
                {p.childrenLoading ? (
                  <div className="flex items-center gap-2 px-2 py-2 text-[11px] text-[var(--muted-foreground)]">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    {t("Loading…")}
                  </div>
                ) : p.children.length === 0 ? (
                  <div className="px-2 py-2 text-[11px] text-[var(--muted-foreground)]">
                    {t("Nothing inside.")}
                  </div>
                ) : (
                  <ul className="max-h-56 space-y-0.5 overflow-y-auto pr-0.5">
                    {p.children.map((c) => {
                      const checked =
                        !!sel && (sel.mode === "all" || sel.ids.has(c.id));
                      const knownChildren = p.children.map((x) => x.id);
                      return (
                        <li key={String(c.id)}>
                          <button
                            type="button"
                            onClick={() =>
                              onToggleChild(p.id, c.id, knownChildren)
                            }
                            className={`flex w-full items-start gap-2.5 rounded px-2 py-1 text-left text-[12px] transition-colors ${
                              checked
                                ? "bg-[var(--primary)]/10"
                                : "hover:bg-[var(--muted)]/60"
                            }`}
                          >
                            <span className="pt-0.5">
                              <CheckBox state={checked ? "on" : "off"} />
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-[var(--foreground)]">
                                {c.title}
                              </div>
                              {c.subtitle && (
                                <div className="truncate text-[10.5px] text-[var(--muted-foreground)]">
                                  {c.subtitle}
                                </div>
                              )}
                            </div>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

// ─── proposal form (unchanged) ─────────────────────────────────────────

function ProposalForm({
  proposal,
  onChange,
  selectedKbs,
}: {
  proposal: BookProposal;
  onChange: (p: BookProposal) => void;
  selectedKbs: string[];
}) {
  const { t } = useTranslation();
  const update = (patch: Partial<BookProposal>) =>
    onChange({ ...proposal, ...patch });
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block sm:col-span-2">
        <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
          {t("Title")}
        </span>
        <input
          value={proposal.title}
          onChange={(e) => update({ title: e.target.value })}
          className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)]"
        />
      </label>
      <label className="block sm:col-span-2">
        <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
          {t("Description")}
        </span>
        <textarea
          value={proposal.description}
          onChange={(e) => update({ description: e.target.value })}
          rows={3}
          className="mt-1 w-full resize-none rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)]"
        />
      </label>
      <label className="block">
        <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
          {t("Scope")}
        </span>
        <input
          value={proposal.scope}
          onChange={(e) => update({ scope: e.target.value })}
          className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)]"
        />
      </label>
      <label className="block">
        <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
          {t("Target level")}
        </span>
        <input
          value={proposal.target_level}
          onChange={(e) => update({ target_level: e.target.value })}
          className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)]"
        />
      </label>
      <label className="block">
        <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
          {t("Estimated chapters")}
        </span>
        <input
          type="number"
          min={2}
          max={12}
          value={proposal.estimated_chapters}
          onChange={(e) =>
            update({ estimated_chapters: Number(e.target.value) || 0 })
          }
          className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)]"
        />
      </label>
      <div className="block sm:col-span-2">
        <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
          {t("Knowledge bases used")}
        </span>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {selectedKbs.length === 0 ? (
            <span className="text-xs italic text-[var(--muted-foreground)]">
              {t(
                "No knowledge bases selected. The book will rely on general knowledge.",
              )}
            </span>
          ) : (
            selectedKbs.map((kb) => (
              <span
                key={kb}
                className="inline-flex items-center rounded-full border border-[var(--border)] bg-[var(--muted)]/40 px-2.5 py-0.5 text-[11px] text-[var(--foreground)]"
              >
                {kb}
              </span>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
