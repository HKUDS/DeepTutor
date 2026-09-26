"use client";

import { BOOKS_HOME } from "@/lib/learning-routes";

/**
 * The Activity home lists the conversation's tools, references, and files.
 * Clicking a file opens it as a tab in SessionViewerPanel. Empty groups are
 * omitted, so the panel remains a short index as a conversation grows.
 */

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  AtSign,
  BookOpen,
  Brain,
  ChevronRight,
  ClipboardList,
  Database,
  ExternalLink,
  History,
  NotebookPen,
  Paperclip,
  Sparkles,
  UserRound,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { docIconFor, formatBytes, isSvgFilename } from "@/lib/doc-attachments";
import type { MessageAttachment } from "@/features/chat/ChatStateAdapter";
import { listSessions, type SessionSummary } from "@/lib/session-api";
import { listNotebooks, type NotebookSummary } from "@/lib/notebook-api";
import { bookApi } from "@/lib/book-api";
import type { Book } from "@/lib/book-types";

import {
  artifactDiskPath,
  type AttachmentWithOrigin,
  type SessionActivity,
  type SpaceReferenceSummary,
} from "@/lib/session-activity";

// Re-exported so existing importers (page.tsx, SessionViewerPanel) keep reaching
// the panel for its own contract while the fold itself lives in lib/.
export type {
  AttachmentWithOrigin,
  SessionActivity,
  SpaceReferenceSummary,
  ToolUsage,
} from "@/lib/session-activity";
export { buildSessionActivity } from "@/lib/session-activity";

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
    href: BOOKS_HOME,
    label: "Books",
    icon: BookOpen,
  },
  notebooks: {
    key: "notebooks",
    href: "/notebooks",
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

/* Activity home surface, shared with SessionViewerPanel's Open section.
   Groups are soft filled tiles under a small label — no border, no shadow —
   so they sit inside the viewer sheet without drawing a frame within a frame.
   (color-mix rather than `bg-[var(--x)]/NN`: Tailwind 3 emits nothing for an
   opacity modifier on a hex CSS variable.) */
export const ACTIVITY_LABEL =
  "px-1.5 pb-1.5 text-[12px] font-medium text-[var(--muted-foreground)]";
export const ACTIVITY_TILE =
  "rounded-xl bg-[color-mix(in_srgb,var(--muted)_45%,transparent)]";
export const ACTIVITY_ROW_HOVER =
  "hover:bg-[color-mix(in_srgb,var(--muted)_95%,transparent)]";

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
  const { tools, knowledgeBases, space, attachments, artifacts } = activity;
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
      <section>
        <h2 className={ACTIVITY_LABEL}>{t("Session activity")}</h2>
        <div className={`${ACTIVITY_TILE} flex items-start gap-3 px-3.5 py-3`}>
          <Wrench
            size={15}
            strokeWidth={1.7}
            aria-hidden="true"
            className="mt-[3px] shrink-0 text-[var(--muted-foreground)]"
          />
          <p className="min-w-0 text-[12.5px] leading-[1.65] text-[var(--muted-foreground)]">
            {t(
              "As you chat, the tools and references you use — and the files the tutor generates — will appear here.",
            )}
          </p>
        </div>
      </section>
    );
  }

  return (
    <div className="space-y-5">
      {!activity.isEmpty ? (
        <section>
        <h2 className={ACTIVITY_LABEL}>{t("Session activity")}</h2>
        <div className={`${ACTIVITY_TILE} divide-y divide-[color-mix(in_srgb,var(--border)_55%,transparent)] overflow-hidden`}>
        {tools.length > 0 ? (
          <SectionCard icon={Wrench} title={t("Tools used")} count={tools.length}>
            <ul className="px-2 pb-2">
              {tools.map((tool) => (
                <li
                  key={tool.name}
                  className="flex min-h-8 items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-[12px] text-[var(--foreground)]"
                >
                  <span className="truncate font-medium">{tool.name}</span>
                  <span className="shrink-0 text-[11px] tabular-nums text-[var(--muted-foreground)]">
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
            <ul className="px-2 pb-2">
              {knowledgeBases.map((kb) => (
                <li
                  key={kb}
                  className="min-h-8 truncate rounded-lg px-2.5 py-1.5 text-[12px] font-medium text-[var(--foreground)]"
                >
                  {kb}
                </li>
              ))}
            </ul>
          </SectionCard>
        ) : null}

        {spaceSubsections.length > 0 ? (
          <SectionCard icon={AtSign} title={t("Space")}>
            <div className="space-y-1 px-2 pb-2">{spaceSubsections}</div>
          </SectionCard>
        ) : null}

        {/* Above Attachments: what this conversation produced is what you come
            back for, more often than a file you uploaded and already have. */}
        {artifacts.length > 0 ? (
          <SectionCard
            icon={Sparkles}
            title={t("Generated files")}
            count={artifacts.length}
          >
            <ul className="px-2 pb-2">
              {artifacts.map(({ attachment, messageIndex }, i) => (
                <AttachmentRow
                  key={`${attachment.id ?? attachment.filename ?? i}-${messageIndex}`}
                  attachment={attachment}
                  onOpen={() => onOpenAttachment(attachment)}
                />
              ))}
            </ul>
          </SectionCard>
        ) : null}

        {attachments.length > 0 ? (
          <SectionCard
            icon={Paperclip}
            title={t("Attachments")}
            count={attachments.length}
          >
            <ul className="px-2 pb-2">
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
        </div>
        </section>
      ) : null}

      {configSection}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Compact section primitives                                         */
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
    <section>
      <header className="flex items-center gap-2.5 px-3.5 pb-1 pt-3">
        <Icon
          size={14}
          strokeWidth={1.8}
          className="shrink-0 text-[var(--muted-foreground)]"
        />
        <h3 className="flex-1 text-[12.5px] font-semibold text-[var(--foreground)]">
          {title}
        </h3>
        {count !== undefined && count > 0 ? (
          <span className="shrink-0 text-[11px] tabular-nums text-[var(--muted-foreground)]">
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
  const { t } = useTranslation();
  return (
    <div>
      <Link
        href={category.href}
        className={`group flex min-h-8 items-center gap-2 rounded-lg px-2.5 py-1 transition-colors ${ACTIVITY_ROW_HOVER} focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--ring)]`}
      >
        <Icon
          size={12}
          strokeWidth={1.8}
          className="shrink-0 text-[var(--muted-foreground)]"
        />
        <span className="flex-1 truncate text-[11.5px] font-medium text-[var(--foreground)] transition-colors group-hover:text-[var(--primary)]">
          {t(category.label)}
        </span>
        <span className="text-[11px] tabular-nums text-[var(--muted-foreground)]">
          {count}
        </span>
        <ExternalLink
          size={10}
          strokeWidth={2}
          aria-hidden="true"
          className="shrink-0 text-[var(--muted-foreground)] opacity-0 transition-opacity group-hover:opacity-100"
        />
      </Link>
      <ul className="ml-[21px] border-l border-[color-mix(in_srgb,var(--border)_70%,transparent)] pl-2">{children}</ul>
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
    <li className="flex min-h-7 items-center gap-2 rounded-md px-2 py-1 text-[11.5px]">
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
  // Generated files carry a size; showing it distinguishes a real deliverable
  // from an empty stub without opening it. The hover title answers "where did
  // this land on disk?" — the question the transcript cannot.
  const size = attachment.generated
    ? formatBytes(attachment.size_bytes ?? -1)
    : "";
  const detail = [spec.label, size].filter(Boolean).join(" · ");
  const diskPath = attachment.generated
    ? artifactDiskPath(attachment.url)
    : null;

  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        title={diskPath ?? undefined}
        className={`group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${ACTIVITY_ROW_HOVER} focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--ring)]`}
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--card)]">
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
          <span className="block truncate text-[10.5px] text-[var(--muted-foreground)]">
            {detail}
          </span>
        </span>
        <ChevronRight
          size={14}
          strokeWidth={1.7}
          aria-hidden="true"
          className="shrink-0 text-[var(--muted-foreground)]/65 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
        />
      </button>
    </li>
  );
}
