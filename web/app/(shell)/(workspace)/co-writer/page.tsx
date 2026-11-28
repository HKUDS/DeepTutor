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
  Trash2,
  Upload,
} from "lucide-react";
import {
  FeaturePage,
  PageHeader,
  pageActionClass,
} from "@/components/layout/FeaturePage";
import { deleteCoWriterDocument, importCoWriterDocx } from "@/lib/co-writer-api";
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
  onDelete,
}: {
  page: NoteSummary;
  parent?: NoteSummary;
  childCount: number;
  locale: string;
  busy: boolean;
  onPin: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpenState] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const setOpen = (value: boolean | ((current: boolean) => boolean)) => {
    const next = typeof value === "function" ? value(open) : value;
    setOpenState(next);
    if (!next) setConfirming(false);
  };
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
            {confirming ? (
              <>
                <p className="dt-notes-confirm">
                  {childCount > 0
                    ? t("Delete this page? Its subpages move up one level.")
                    : t("Delete this page? This cannot be undone.")}
                </p>
                <button
                  role="menuitem"
                  className="dt-menu-item is-danger"
                  onClick={() => {
                    setOpen(false);
                    onDelete();
                  }}
                >
                  <Trash2 size={14} />
                  {t("Delete page")}
                </button>
              </>
            ) : (
              <button role="menuitem" className="dt-menu-item is-danger" onClick={() => setConfirming(true)}>
                <Trash2 size={14} />
                {t("Delete")}
              </button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

export default function CoWriterHomePage() {
  const router = useRouter();
  const { t, i18n } = useTranslation();
  const [pages, setPages] = useState<NoteSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
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

  const handleImportDocx = useCallback(
    async (file: File | undefined) => {
      if (!file || creating || importing) return;
      setImporting(true);
      setError("");
      try {
        const document = await importCoWriterDocx(file);
        notifyCoWriterChanged();
        router.push(`/co-writer/${document.id}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setImporting(false);
      }
    },
    [creating, importing, router],
  );

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

  const handleDelete = async (page: NoteSummary) => {
    setBusyId(page.id);
    try {
      await deleteCoWriterDocument(page.id);
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
  // Browsing shows the notebook's top level; a search reaches every page.
  const visible = needle
    ? pages.filter((page) =>
        `${page.title} ${page.preview}`.toLocaleLowerCase().includes(needle),
      )
    : pages.filter((page) => !page.parent_id || !byId.has(page.parent_id));
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
      onDelete={() => void handleDelete(page)}
    />
  );

  return (
    <FeaturePage>
      <input
        ref={importInputRef}
        type="file"
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          void handleImportDocx(file);
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
              {t("Import Word")}
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
              {t("Import Word")}
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="dt-notes-toolbar">
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
              {t("{{count}} pages", { count: pages.length })}
            </span>
          </div>
          {!visible.length && (
            <p className="dt-notes-none">{t("No pages match “{{query}}”.", { query: query.trim() })}</p>
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
