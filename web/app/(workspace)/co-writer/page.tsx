"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  FileText,
  Loader2,
  MoreHorizontal,
  PenLine,
  Pin,
  PinOff,
  Plus,
  Search,
  Upload,
} from "lucide-react";
import {
  FeaturePage,
  PageHeader,
  pageActionClass,
} from "@/components/layout/FeaturePage";
import { deleteCoWriterDocument } from "@/lib/co-writer-api";
import NotePageActions, { type PageAction } from "@/features/notes/components/NotePageActions";
import { noteDocumentTypes } from "@/features/notes/model/import-document";
import { useNoteImport } from "@/features/notes/components/useNoteImport";
import { useNoteDestination } from "@/features/notes/components/useNoteNavigation";
import { activePages } from "@/features/notes/model/page-tree";
import { notifyCoWriterChanged } from "@/lib/co-writer-events";
import { createNote, listNotes, saveNote, type NoteSummary } from "@/lib/notes-api";
import { formatRelativeTime } from "@/lib/relative-time";
import { useMenuPopover } from "@/shared/ui/useMenuPopover";
import "@/features/notes/components/note-library.css";

const NoteReview = dynamic(() => import("@/features/notes/components/NoteReview"), {
  ssr: false,
});

function PageCard({
  page,
  parent,
  childCount,
  locale,
  busy,
  onPin,
  onAction,
}: {
  page: NoteSummary;
  parent?: NoteSummary;
  childCount: number;
  locale: string;
  busy: boolean;
  onPin: () => void;
  onAction: (action: PageAction) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const menu = useMenuPopover<HTMLDivElement>(open, setOpen);
  const title = page.title || t("Untitled");
  return (
    <article className={`dt-notes-card ${page.cover ? "has-cover" : ""} ${open ? "is-menu-open" : ""}`}>
      <Link href={`/co-writer/${page.id}`} className="dt-notes-card-link" aria-label={title}>
        {page.cover ? <div className="dt-notes-card-cover" style={{ background: page.cover }} /> : null}
        <div className="dt-notes-card-body">
          <span className="dt-notes-card-icon" aria-hidden>
            {page.icon || <FileText size={18} strokeWidth={1.6} />}
          </span>
          <h3>{title}</h3>
          <p className={page.preview ? "" : "is-empty"}>{page.preview || t("Empty page")}</p>
          <footer>
            {page.pinned && <Pin size={11} aria-label={t("Pinned page")} />}
            {parent && <span className="truncate">{parent.title || t("Untitled")}</span>}
            {parent && <span aria-hidden>·</span>}
            <span>{formatRelativeTime(page.updated_at, locale)}</span>
            {childCount > 0 && (
              <>
                <span aria-hidden>·</span>
                <span>{t("{{count}} subpages", { count: childCount })}</span>
              </>
            )}
          </footer>
        </div>
      </Link>
      <div ref={menu} className="dt-notes-card-menu">
        <button
          className="dt-note-icon-button"
          aria-label={t("Page actions for {{page}}", { page: title })}
          aria-haspopup="menu"
          aria-expanded={open}
          disabled={busy}
          onClick={() => setOpen(!open)}
        >
          <MoreHorizontal size={16} strokeWidth={1.7} />
        </button>
        {open && (
          <div className="dt-popover dt-notes-card-popover" role="menu">
            <button
              role="menuitem"
              className="dt-menu-item"
              onClick={() => {
                setOpen(false);
                onPin();
              }}
            >
              {page.pinned ? <PinOff size={14} /> : <Pin size={14} />}
              {t(page.pinned ? "Unpin" : "Pin to top")}
            </button>
            <div className="dt-menu-divider" />
            <NotePageActions compact page={page} hasChildren={childCount > 0} onAction={action => {
              setOpen(false);
              onAction(action);
            }} />
          </div>
        )}
      </div>
    </article>
  );
}

export default function CoWriterHomePage() {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const initial = useNoteDestination();
  const [pages, setPages] = useState<NoteSummary[]>(initial?.pages ?? []);
  const [loading, setLoading] = useState(!initial);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState("");
  const { openFile, importing, dialog } = useNoteImport(pages, setError);
  const importInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setError("");
    try {
      setPages((await listNotes()).documents);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = useCallback(async () => {
    if (creating) return;
    setCreating(true);
    setError("");
    try {
      const page = await createNote("");
      notifyCoWriterChanged();
      router.push(`/co-writer/${page.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setCreating(false);
    }
  }, [creating, router]);

  const handlePin = async (page: NoteSummary) => {
    setBusyId(page.id);
    try {
      await saveNote(page.id, { pinned: !page.pinned, expected_revision: page.revision });
      notifyCoWriterChanged();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const handleAction = async (page: NoteSummary, action: PageAction) => {
    setBusyId(page.id);
    try {
      if (action === "delete") await deleteCoWriterDocument(page.id);
      else await saveNote(page.id, { archived: action === "archive", expected_revision: page.revision });
      notifyCoWriterChanged();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const byId = useMemo(() => new Map(pages.map((page) => [page.id, page])), [pages]);
  const childCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const page of pages)
      if (page.parent_id) counts.set(page.parent_id, (counts.get(page.parent_id) ?? 0) + 1);
    return counts;
  }, [pages]);
  const needle = query.trim().toLocaleLowerCase();
  const scope = showArchived ? pages.filter(page => page.archived) : activePages(pages);
  // Browsing shows the notebook's top level; a search reaches every page.
  const visible = needle
    ? scope.filter((page) =>
        `${page.title} ${page.preview}`.toLocaleLowerCase().includes(needle),
      )
    : scope.filter((page) => showArchived || !page.parent_id || !byId.has(page.parent_id));
  const pinned = visible.filter((page) => page.pinned);
  const rest = visible.filter((page) => !page.pinned);

  const card = (page: NoteSummary) => (
    <PageCard
      key={page.id}
      page={page}
      parent={needle && page.parent_id ? byId.get(page.parent_id) : undefined}
      childCount={childCounts.get(page.id) ?? 0}
      locale={i18n.language}
      busy={busyId === page.id}
      onPin={() => void handlePin(page)}
      onAction={action => void handleAction(page, action)}
    />
  );

  return (
    <FeaturePage>
      {dialog}
      <input
        ref={importInputRef}
        type="file"
        accept={noteDocumentTypes}
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (file && !creating && !importing) void openFile(file);
        }}
      />
      <PageHeader
        icon={PenLine}
        title={t("Learning notebook")}
        description={t("Pages for what you are learning — write, link, and study them with Dito.")}
        action={
          <div className="flex shrink-0 items-center gap-2">
            <NoteReview />
            <button
              type="button"
              onClick={() => importInputRef.current?.click()}
              disabled={creating || importing}
              className={pageActionClass("secondary")}
            >
              {importing ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              {t("Import document")}
            </button>
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={creating || importing}
              className={pageActionClass()}
            >
              {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              {t("New page")}
            </button>
          </div>
        }
      />

      {error ? <div className="dt-notes-error" role="alert">{error}</div> : null}

      {loading ? (
        <div className="dt-notes-skeleton" aria-busy="true" aria-label={t("Loading pages…")}>
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} />
          ))}
        </div>
      ) : pages.length === 0 ? (
        <div className="dt-notes-empty">
          <span aria-hidden>📓</span>
          <h2>{t("Your notebook is empty")}</h2>
          <p>{t("Start a page for a topic, a lecture or a paper. Dito can help you write and turn it into practice.")}</p>
          <div>
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={creating || importing}
              className={pageActionClass()}
            >
              <Plus size={14} />
              {t("New page")}
            </button>
            <button
              type="button"
              onClick={() => importInputRef.current?.click()}
              disabled={creating || importing}
              className={pageActionClass("secondary")}
            >
              <Upload size={14} />
              {t("Import document")}
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="dt-notes-toolbar">
            <button type="button" className={pageActionClass("secondary")} aria-pressed={showArchived}
              onClick={() => setShowArchived(!showArchived)}>
              {t("Archived")}
            </button>
            <label className="dt-notes-search">
              <Search size={14} strokeWidth={1.8} aria-hidden />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("Search pages…")}
                aria-label={t("Search pages")}
              />
            </label>
            <span className="dt-notes-count">
              {t("{{count}} pages", { count: scope.length })}
            </span>
          </div>
          {!visible.length && (
            <p className="dt-notes-none">{needle ? t("No pages match “{{query}}”.", { query: query.trim() })
              : t(showArchived ? "No archived pages" : "No active pages")}</p>
          )}
          {!!pinned.length && (
            <section className="dt-notes-section" aria-label={t("Pinned pages")}>
              <h2>{t("Pinned pages")}</h2>
              <div className="dt-notes-grid">{pinned.map(card)}</div>
            </section>
          )}
          {!!rest.length && (
            <section className="dt-notes-section" aria-label={t(needle ? "Results" : "Recently edited")}>
              {(pinned.length > 0 || needle) && <h2>{t(needle ? "Results" : "Recently edited")}</h2>}
              <div className="dt-notes-grid">{rest.map(card)}</div>
            </section>
          )}
        </>
      )}
    </FeaturePage>
  );
}
