"use client";

/**
 * SessionActivityPanel — right-side column of *floating cards* recording
 * the conversation's tools, knowledge bases, Space refs, and attachments.
 *
 * Design notes
 * ────────────
 * • The panel itself has **no background** — cards float over the page so
 *   the chat surface still bleeds through. Each card carries its own border
 *   + faint shadow so it reads as a discrete block.
 * • Clicking an attachment row fires `onOpenAttachment(att)` upward; the
 *   parent routes it into the SessionViewerPanel as a new file tab.
 * • Section content is suppressed entirely when empty — no skeleton cards
 *   for tools/KBs/Space/attachments that never showed up in this session.
 */

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  AtSign,
  BookOpen,
  Brain,
  ClipboardList,
  Database,
  ExternalLink,
  History,
  NotebookPen,
  Paperclip,
  UserRound,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { docIconFor, isSvgFilename } from "@/lib/doc-attachments";
import type {
  MessageAttachment,
  MessageItem,
  MessageRequestSnapshot,
} from "@/context/UnifiedChatContext";
import type { StreamEvent } from "@/lib/unified-ws";
import { listSessions, type SessionSummary } from "@/lib/session-api";
import { listNotebooks, type NotebookSummary } from "@/lib/notebook-api";
import { bookApi } from "@/lib/book-api";
import type { Book } from "@/lib/book-types";

/* ------------------------------------------------------------------ */
/*  Aggregator                                                         */
/* ------------------------------------------------------------------ */

export interface ToolUsage {
  name: string;
  count: number;
}

export interface AttachmentWithOrigin {
  messageIndex: number;
  attachment: MessageAttachment;
}

export interface SpaceReferenceSummary {
  historySessionIds: string[];
  bookPageCount: number;
  bookIds: string[];
  bookPages: Map<string, string[]>;
  notebookRecordCount: number;
  notebookIds: string[];
  questionEntryIds: number[];
  personas: string[];
  memoryKinds: Array<"summary" | "profile">;
}

export interface SessionActivity {
  tools: ToolUsage[];
  knowledgeBases: string[];
  space: SpaceReferenceSummary;
  attachments: AttachmentWithOrigin[];
  isEmpty: boolean;
}

export function buildSessionActivity(messages: MessageItem[]): SessionActivity {
  const toolCounts = new Map<string, number>();
  const kbs = new Set<string>();
  const historySessionIds = new Set<string>();
  const bookIds = new Set<string>();
  const bookPages = new Map<string, string[]>();
  let bookPageCount = 0;
  const notebookIds = new Set<string>();
  let notebookRecordCount = 0;
  const questionEntryIds = new Set<number>();
  const personas = new Set<string>();
  const memoryKinds = new Set<"summary" | "profile">();
  const attachments: AttachmentWithOrigin[] = [];

  messages.forEach((msg, idx) => {
    msg.events?.forEach((event: StreamEvent) => {
      if (event.type !== "tool_call") return;
      const name =
        String((event.metadata as { tool?: string } | undefined)?.tool || "") ||
        event.content?.trim() ||
        "tool";
      toolCounts.set(name, (toolCounts.get(name) ?? 0) + 1);
    });

    msg.attachments?.forEach((a) => {
      attachments.push({ messageIndex: idx, attachment: a });
    });

    const snap: MessageRequestSnapshot | undefined = msg.requestSnapshot;
    if (snap) {
      snap.knowledgeBases?.forEach((k) => kbs.add(k));
      snap.historyReferences?.forEach((s) => historySessionIds.add(s));
      snap.bookReferences?.forEach((b) => {
        bookIds.add(b.book_id);
        bookPageCount += b.page_ids?.length ?? 0;
        const existing = bookPages.get(b.book_id) ?? [];
        bookPages.set(b.book_id, [...existing, ...(b.page_ids ?? [])]);
      });
      snap.notebookReferences?.forEach((n) => {
        notebookIds.add(n.notebook_id);
        notebookRecordCount += n.record_ids?.length ?? 0;
      });
      snap.questionNotebookReferences?.forEach((q) => questionEntryIds.add(q));
      if (snap.persona) personas.add(snap.persona);
      snap.memoryReferences?.forEach((k) => memoryKinds.add(k));
    }
  });

  const tools = Array.from(toolCounts.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));

  const space: SpaceReferenceSummary = {
    historySessionIds: Array.from(historySessionIds),
    bookPageCount,
    bookIds: Array.from(bookIds),
    bookPages,
    notebookRecordCount,
    notebookIds: Array.from(notebookIds),
    questionEntryIds: Array.from(questionEntryIds),
    personas: Array.from(personas),
    memoryKinds: Array.from(memoryKinds),
  };

  const isEmpty =
    tools.length === 0 &&
    kbs.size === 0 &&
    attachments.length === 0 &&
    space.historySessionIds.length === 0 &&
    space.bookIds.length === 0 &&
    space.notebookIds.length === 0 &&
    space.questionEntryIds.length === 0 &&
    space.personas.length === 0 &&
    space.memoryKinds.length === 0;

  return {
    tools,
    knowledgeBases: Array.from(kbs),
    space,
    attachments,
    isEmpty,
  };
}

/* ------------------------------------------------------------------ */
/*  Title resolver — lazy id -> title for Space items                  */
/* ------------------------------------------------------------------ */

interface ResolvedTitles {
  sessions: Map<string, string>;
  notebooks: Map<string, string>;
  books: Map<string, string>;
}

function useResolvedTitles(
  activity: SessionActivity,
  open: boolean,
): ResolvedTitles {
  const [sessions, setSessions] = useState<Map<string, string>>(new Map());
  const [notebooks, setNotebooks] = useState<Map<string, string>>(new Map());
  const [books, setBooks] = useState<Map<string, string>>(new Map());

  const needsSessions = activity.space.historySessionIds.length > 0;
  const needsNotebooks = activity.space.notebookIds.length > 0;
  const needsBooks = activity.space.bookIds.length > 0;

  useEffect(() => {
    if (!open || !needsSessions || sessions.size > 0) return;
    let cancelled = false;
    listSessions(200)
      .then((rows: SessionSummary[]) => {
        if (cancelled) return;
        const map = new Map<string, string>();
        rows.forEach((r) => map.set(r.session_id, r.title || r.session_id));
        setSessions(map);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [open, needsSessions, sessions.size]);

  useEffect(() => {
    if (!open || !needsNotebooks || notebooks.size > 0) return;
    let cancelled = false;
    listNotebooks()
      .then((rows: NotebookSummary[]) => {
        if (cancelled) return;
        const map = new Map<string, string>();
        rows.forEach((r) => map.set(r.id, r.name || r.id));
        setNotebooks(map);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [open, needsNotebooks, notebooks.size]);

  useEffect(() => {
    if (!open || !needsBooks || books.size > 0) return;
    let cancelled = false;
    bookApi
      .list()
      .then(({ books: rows }: { books: Book[] }) => {
        if (cancelled) return;
        const map = new Map<string, string>();
        rows.forEach((r) => map.set(r.id, r.title || r.id));
        setBooks(map);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [open, needsBooks, books.size]);

  return { sessions, notebooks, books };
}

/* ------------------------------------------------------------------ */
/*  Activity body                                                      */
/*                                                                     */
/*  Rendered as the "Activity" home view inside SessionViewerPanel (it */
/*  used to live in its own floating-card panel; the two were merged   */
/*  so the session's activity is the viewer's landing and files open   */
/*  as tabs alongside it).                                             */
/* ------------------------------------------------------------------ */

interface SpaceCategoryDef {
  key: string;
  href: string;
  label: string;
  icon: LucideIcon;
}

const SPACE_CATEGORIES: Record<string, SpaceCategoryDef> = {
  chat_history: {
    key: "chat_history",
    href: "/space/chat-history",
    label: "Chat history",
    icon: History,
  },
  books: {
    key: "books",
    href: "/space/books",
    label: "Books",
    icon: BookOpen,
  },
  notebooks: {
    key: "notebooks",
    href: "/space/notebooks",
    label: "Notebooks",
    icon: NotebookPen,
  },
  question_bank: {
    key: "question_bank",
    href: "/space/questions",
    label: "Question bank",
    icon: ClipboardList,
  },
  persona: {
    key: "persona",
    href: "/space/personas",
    label: "Persona",
    icon: UserRound,
  },
  memory: {
    key: "memory",
    href: "/memory",
    label: "Memory",
    icon: Brain,
  },
};

export function ActivityBody({
  activity,
  open,
  onOpenAttachment,
  configSection,
}: {
  activity: SessionActivity;
  open: boolean;
  onOpenAttachment: (a: MessageAttachment) => void;
  configSection?: ReactNode;
}) {
  const { t } = useTranslation();
  const { tools, knowledgeBases, space, attachments } = activity;
  const { sessions, notebooks, books } = useResolvedTitles(activity, open);

  const spaceSubsections: ReactNode[] = [];
  if (space.historySessionIds.length > 0) {
    spaceSubsections.push(
      <SpaceSubsection
        key="chat_history"
        category={SPACE_CATEGORIES.chat_history}
        count={space.historySessionIds.length}
      >
        {space.historySessionIds.map((id) => (
          <SpaceItemRow
            key={id}
            title={sessions.get(id) ?? id}
            subtitle={id.slice(0, 8)}
          />
        ))}
      </SpaceSubsection>,
    );
  }
  if (space.bookIds.length > 0) {
    spaceSubsections.push(
      <SpaceSubsection
        key="books"
        category={SPACE_CATEGORIES.books}
        count={space.bookIds.length}
      >
        {space.bookIds.map((id) => {
          const pages = space.bookPages.get(id)?.length ?? 0;
          return (
            <SpaceItemRow
              key={id}
              title={books.get(id) ?? id}
              subtitle={t("{{n}} page(s)", { n: pages })}
            />
          );
        })}
      </SpaceSubsection>,
    );
  }
  if (space.notebookIds.length > 0) {
    spaceSubsections.push(
      <SpaceSubsection
        key="notebooks"
        category={SPACE_CATEGORIES.notebooks}
        count={space.notebookIds.length}
      >
        {space.notebookIds.map((id) => (
          <SpaceItemRow key={id} title={notebooks.get(id) ?? id} />
        ))}
      </SpaceSubsection>,
    );
  }
  if (space.questionEntryIds.length > 0) {
    spaceSubsections.push(
      <SpaceSubsection
        key="question_bank"
        category={SPACE_CATEGORIES.question_bank}
        count={space.questionEntryIds.length}
      >
        {space.questionEntryIds.map((id) => (
          <SpaceItemRow key={id} title={t("Question #{{n}}", { n: id })} />
        ))}
      </SpaceSubsection>,
    );
  }
  if (space.personas.length > 0) {
    spaceSubsections.push(
      <SpaceSubsection
        key="persona"
        category={SPACE_CATEGORIES.persona}
        count={space.personas.length}
      >
        {space.personas.map((persona) => (
          <SpaceItemRow key={persona} title={persona} />
        ))}
      </SpaceSubsection>,
    );
  }
  if (space.memoryKinds.length > 0) {
    spaceSubsections.push(
      <SpaceSubsection
        key="memory"
        category={SPACE_CATEGORIES.memory}
        count={space.memoryKinds.length}
      >
        {space.memoryKinds.map((kind) => (
          <SpaceItemRow key={kind} title={kind} />
        ))}
      </SpaceSubsection>,
    );
  }

  if (activity.isEmpty && !configSection) {
    return (
      <SectionCard icon={Wrench} title={t("Session activity")}>
        <div className="px-3.5 py-5 text-center text-[12px] italic text-[var(--muted-foreground)]/80">
          {t(
            "As you chat, the tools, references and attachments you use will appear here.",
          )}
        </div>
      </SectionCard>
    );
  }

  return (
    <div className="space-y-2.5">
      {tools.length > 0 ? (
        <SectionCard icon={Wrench} title={t("Tools used")} count={tools.length}>
          <ul className="space-y-0.5 p-1.5">
            {tools.map((tool) => (
              <li
                key={tool.name}
                className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-[12px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/35"
              >
                <span className="truncate font-medium">{tool.name}</span>
                <span className="shrink-0 rounded-full bg-[var(--muted)]/55 px-1.5 py-[1px] text-[10px] font-semibold text-[var(--muted-foreground)]">
                  ×{tool.count}
                </span>
              </li>
            ))}
          </ul>
        </SectionCard>
      ) : null}

      {knowledgeBases.length > 0 ? (
        <SectionCard
          icon={Database}
          title={t("Knowledge bases")}
          count={knowledgeBases.length}
        >
          <ul className="space-y-0.5 p-1.5">
            {knowledgeBases.map((kb) => (
              <li
                key={kb}
                className="truncate rounded-md px-2 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/35"
              >
                {kb}
              </li>
            ))}
          </ul>
        </SectionCard>
      ) : null}

      {spaceSubsections.length > 0 ? (
        <SectionCard icon={AtSign} title={t("Space")}>
          <div className="space-y-1.5 p-1.5">{spaceSubsections}</div>
        </SectionCard>
      ) : null}

      {attachments.length > 0 ? (
        <SectionCard
          icon={Paperclip}
          title={t("Attachments")}
          count={attachments.length}
        >
          <ul className="space-y-0.5 p-1.5">
            {attachments.map(({ attachment, messageIndex }, i) => (
              <AttachmentRow
                key={`${attachment.id ?? attachment.filename ?? i}-${messageIndex}`}
                attachment={attachment}
                onOpen={() => onOpenAttachment(attachment)}
              />
            ))}
          </ul>
        </SectionCard>
      ) : null}

      {configSection}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Card primitives                                                    */
/* ------------------------------------------------------------------ */

function SectionCard({
  icon: Icon,
  title,
  count,
  children,
}: {
  icon: LucideIcon;
  title: string;
  count?: number;
  children: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-[var(--border)]/55 bg-[var(--card)] shadow-[0_1px_2px_color-mix(in_srgb,var(--foreground)_5%,transparent),0_4px_14px_color-mix(in_srgb,var(--foreground)_5%,transparent)]">
      <header className="flex items-center gap-2 border-b border-[var(--border)]/35 px-3.5 py-2.5">
        <Icon
          size={13}
          strokeWidth={1.8}
          className="shrink-0 text-[var(--muted-foreground)]"
        />
        <span className="flex-1 text-[12px] font-semibold tracking-[0.005em] text-[var(--foreground)]">
          {title}
        </span>
        {count !== undefined && count > 0 ? (
          <span className="shrink-0 rounded-full bg-[var(--muted)]/55 px-1.5 py-[1px] text-[10px] font-semibold text-[var(--muted-foreground)]">
            {count}
          </span>
        ) : null}
      </header>
      {children}
    </section>
  );
}

function SpaceSubsection({
  category,
  count,
  children,
}: {
  category: SpaceCategoryDef;
  count: number;
  children: ReactNode;
}) {
  const Icon = category.icon;
  return (
    <div>
      <Link
        href={category.href}
        className="group flex items-center gap-2 rounded-md px-2 py-1 transition-colors hover:bg-[var(--muted)]/40"
      >
        <Icon
          size={12}
          strokeWidth={1.8}
          className="shrink-0 text-[var(--muted-foreground)]"
        />
        <span className="flex-1 truncate text-[10.5px] font-semibold uppercase tracking-[0.06em] text-[var(--muted-foreground)] transition-colors group-hover:text-[var(--primary)]">
          {category.label}
        </span>
        <span className="rounded-full bg-[var(--muted)]/55 px-1.5 py-[1px] text-[10px] font-semibold text-[var(--muted-foreground)]">
          {count}
        </span>
        <ExternalLink
          size={10}
          strokeWidth={2}
          className="shrink-0 text-[var(--muted-foreground)] opacity-0 transition-opacity group-hover:opacity-100"
        />
      </Link>
      <ul className="mt-0.5 space-y-px pl-5">{children}</ul>
    </div>
  );
}

function SpaceItemRow({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <li className="flex items-center gap-2 rounded-md px-2 py-1 text-[12px] transition-colors hover:bg-[var(--muted)]/35">
      <span className="block min-w-0 flex-1 truncate font-medium text-[var(--foreground)]">
        {title}
      </span>
      {subtitle ? (
        <span className="shrink-0 text-[10px] text-[var(--muted-foreground)]">
          {subtitle}
        </span>
      ) : null}
    </li>
  );
}

function AttachmentRow({
  attachment,
  onOpen,
}: {
  attachment: MessageAttachment;
  onOpen: () => void;
}) {
  const filename = attachment.filename || "untitled";
  const spec = docIconFor(filename);
  const Icon = spec.Icon;
  const isImage = attachment.type === "image" || isSvgFilename(filename);

  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[var(--muted)]/35"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--muted)]/55">
          <Icon
            size={13}
            strokeWidth={1.6}
            className={isImage ? "text-[var(--muted-foreground)]" : spec.tint}
          />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12px] font-medium text-[var(--foreground)]">
            {filename}
          </span>
          <span className="block truncate text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
            {spec.label}
          </span>
        </span>
      </button>
    </li>
  );
}
