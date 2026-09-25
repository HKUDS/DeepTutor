"use client";

import {
  ArrowRight,
  BookOpen,
  ChevronRight,
  CircleAlert,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  Palette,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { LearningSkeleton } from "@/components/learning/LearningShell";
import { useChatWorkspaces } from "@/hooks/useChatWorkspaces";
import {
  READING_HOME,
  readingCollectionRoute,
  readingSessionRoute,
} from "@/lib/learning-routes";
import {
  activateReadingMaterial,
  getReadingWorkspace,
  removeReadingWorkspaceMaterial,
  type ReadingConversation,
  type ReadingWorkspace,
  type ReadingWorkspaceTab,
} from "@/lib/reading-workspace-api";
import { activeWorkspaceId, scopedUrl } from "@/lib/workspace-scope";

import { AddMaterialsDialog } from "./AddMaterialsDialog";
import { FolderDialog } from "./FolderDialog";
import { FolderGlyph } from "./FolderGlyph";
import { DeleteCollectionDialog } from "./ReadingLibrary";
import { MaterialGlyph, materialDetail, relativeDate } from "./shared";

/**
 * A collection opened like a folder: what is in it, what has been said about
 * it, and one way in. Reading always opens the whole folder — every file is a
 * tab of the same reader and shares its conversations — so picking a file here
 * only chooses which tab comes first.
 */
export function ReadingFolderPage({ folderId }: { folderId: string }) {
  const { t, i18n } = useTranslation();
  const router = useRouter();
  const { workspaces } = useChatWorkspaces();
  const [folder, setFolder] = useState<ReadingWorkspace | null>(null);
  const [sessions, setSessions] = useState<ReadingConversation[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [opening, setOpening] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [dialog, setDialog] = useState<"add" | "edit" | "delete" | null>(null);

  // The URL names the workspace the folder is stored in; every request on
  // this page is scoped by it.
  const contentWorkspace = activeWorkspaceId();
  const workspaceLabel =
    workspaces.find((row) => row.workspace_id === contentWorkspace)
      ?.display_name ||
    (contentWorkspace ? contentWorkspace : t("Default workspace"));

  const refresh = useCallback(async () => {
    try {
      const result = await getReadingWorkspace(folderId);
      setFolder(result.workspace);
      setSessions(
        [...result.sessions].sort((a, b) => b.updated_at - a.updated_at),
      );
      setError("");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : t("Could not open this collection."),
      );
    } finally {
      setLoading(false);
    }
  }, [folderId, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Files still being prepared settle on their own; poll until they do so the
  // page never shows a spinner that has long since finished.
  const preparing = Boolean(
    folder?.tabs.some(
      (tab) =>
        tab.material.status === "processing" ||
        tab.material.status === "queued",
    ),
  );
  useEffect(() => {
    if (!preparing) return;
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [preparing, refresh]);

  const readerHref = readingCollectionRoute(folderId, contentWorkspace);

  const openFile = async (tab: ReadingWorkspaceTab) => {
    if (opening) return;
    setOpening(tab.material.material_id);
    try {
      await activateReadingMaterial(folderId, tab.material.material_id);
    } catch {
      // The reader still opens; it just starts on the last active file.
    }
    router.push(readerHref);
  };

  const removeFile = async (tab: ReadingWorkspaceTab) => {
    try {
      setFolder(
        await removeReadingWorkspaceMaterial(folderId, tab.material.material_id),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Could not save."));
    }
  };

  if (loading) {
    return (
      <FolderFrame>
        <LearningSkeleton />
      </FolderFrame>
    );
  }

  if (!folder) {
    return (
      <FolderFrame>
        <div className="flex flex-col items-center py-24 text-center">
          <CircleAlert size={24} className="text-[var(--primary)]" />
          <p className="mt-3 text-[13px] font-medium">{error}</p>
          <Link
            href={scopedUrl(READING_HOME)}
            className="mt-5 rounded-lg bg-[var(--primary)] px-3.5 py-2 text-[12px] font-semibold text-[var(--primary-foreground)]"
          >
            {t("Back to collections")}
          </Link>
        </div>
      </FolderFrame>
    );
  }

  const files = folder.tabs;
  const collection = { ...folder, content_workspace_id: contentWorkspace };

  return (
    <FolderFrame>
      <nav
        aria-label={t("Breadcrumb")}
        className="flex min-w-0 items-center gap-1 text-[12px] text-[var(--muted-foreground)]"
      >
        <Link
          href={scopedUrl(READING_HOME)}
          className="shrink-0 hover:text-[var(--foreground)]"
        >
          {t("Immersive Reading")}
        </Link>
        <ChevronRight size={12} className="shrink-0 opacity-60" />
        <span className="shrink-0">{workspaceLabel}</span>
        <ChevronRight size={12} className="shrink-0 opacity-60" />
        <span className="truncate text-[var(--foreground)]">{folder.title}</span>
      </nav>

      <header className="mt-6 flex flex-col gap-5 sm:flex-row sm:items-end">
        <FolderGlyph
          color={folder.color}
          files={files.length}
          size={84}
          className="shrink-0"
        />
        <div className="min-w-0 flex-1">
          <h1 className="font-serif text-[26px] font-semibold leading-tight tracking-[-0.02em] md:text-[28px]">
            {folder.title}
          </h1>
          <p className="mt-1.5 text-[12.5px] text-[var(--muted-foreground)]">
            {t("{{count}} files", { count: files.length })}
            {" · "}
            {t("Stored in {{workspace}}", { workspace: workspaceLabel })}
          </p>
        </div>
        <div className="relative flex shrink-0 items-center gap-2">
          {files.length ? (
            <Link
              href={readerHref}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 text-[12.5px] font-semibold text-[var(--primary-foreground)] transition hover:opacity-90"
            >
              <BookOpen size={14} />
              {t("Start reading")}
            </Link>
          ) : null}
          <button
            type="button"
            onClick={() => setDialog("add")}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[var(--border)] px-3.5 text-[12.5px] transition hover:bg-[var(--muted)]"
          >
            <Plus size={14} />
            {t("Add material")}
          </button>
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-label={t("Collection menu")}
            aria-expanded={menuOpen}
            className="flex size-9 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition hover:bg-[var(--muted)]"
          >
            <MoreHorizontal size={15} />
          </button>
          {menuOpen && (
            <>
              <div
                className="fixed inset-0 z-10"
                onClick={() => setMenuOpen(false)}
              />
              <div
                role="menu"
                className="absolute right-0 top-11 z-20 w-44 rounded-lg border border-[var(--border)] bg-[var(--card)] p-1 text-[12px] shadow-md dark:bg-[var(--popover)]"
              >
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    setDialog("edit");
                  }}
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left hover:bg-[var(--muted)]"
                >
                  <Palette size={12} />
                  {t("Rename or recolor")}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    setDialog("delete");
                  }}
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-[var(--destructive)] hover:bg-[var(--muted)]"
                >
                  <Trash2 size={12} />
                  {t("Delete collection")}
                </button>
              </div>
            </>
          )}
        </div>
      </header>

      {error && (
        <p role="alert" className="mt-4 text-[12px] text-[var(--destructive)]">
          {error}
        </p>
      )}

      <section className="mt-9">
        <SectionHeading label={t("Files")} count={files.length} />
        {files.length ? (
          <ul className="mt-2 divide-y divide-[var(--border)] border-y border-[var(--border)]">
            {files.map((tab) => (
              <FileRow
                key={tab.material.material_id}
                tab={tab}
                opening={opening === tab.material.material_id}
                onOpen={() => void openFile(tab)}
                onRemove={() => void removeFile(tab)}
              />
            ))}
          </ul>
        ) : (
          <button
            type="button"
            onClick={() => setDialog("add")}
            className="mt-2 flex w-full flex-col items-center gap-1.5 rounded-xl border border-dashed border-[var(--border)] px-6 py-10 text-center transition hover:border-[var(--ring)]"
          >
            <Plus size={16} className="text-[var(--muted-foreground)]" />
            <span className="text-[13px] font-medium">
              {t("This folder is empty")}
            </span>
            <span className="text-[12px] text-[var(--muted-foreground)]">
              {t("Add papers, chapters, web pages or videos to read them together.")}
            </span>
          </button>
        )}
      </section>

      <section className="mt-9">
        <SectionHeading label={t("Conversations")} count={sessions.length} />
        {sessions.length ? (
          <ul className="mt-2 divide-y divide-[var(--border)] border-y border-[var(--border)]">
            {sessions.map((session) => (
              <li key={session.session_id}>
                <Link
                  href={readingSessionRoute(
                    folderId,
                    session.session_id,
                    contentWorkspace,
                  )}
                  className="group flex items-center gap-3 px-1 py-2.5 transition hover:bg-[var(--secondary)]"
                >
                  <MessageSquare
                    size={14}
                    className="shrink-0 text-[var(--muted-foreground)]"
                  />
                  <span className="min-w-0 flex-1 truncate text-[13px]">
                    {session.title || t("New reading conversation")}
                  </span>
                  <span className="shrink-0 text-[11px] text-[var(--muted-foreground)]">
                    {relativeDate(session.updated_at, i18n.language)}
                  </span>
                  <ArrowRight
                    size={13}
                    className="shrink-0 text-[var(--muted-foreground)] opacity-0 transition group-hover:opacity-100"
                  />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 px-1 text-[12px] text-[var(--muted-foreground)]">
            {t("Conversations you have while reading this folder appear here.")}
          </p>
        )}
      </section>

      {dialog === "add" && (
        <AddMaterialsDialog
          mode="add"
          workspaceId={folderId}
          onClose={() => setDialog(null)}
          onDone={() => {
            setDialog(null);
            void refresh();
          }}
        />
      )}
      {dialog === "edit" && (
        <FolderDialog
          collection={collection}
          workspaceId={contentWorkspace}
          onClose={() => setDialog(null)}
          onSaved={(saved) => {
            setDialog(null);
            setFolder(saved);
          }}
        />
      )}
      {dialog === "delete" && (
        <DeleteCollectionDialog
          collection={collection}
          onClose={() => setDialog(null)}
          onDeleted={async () => {
            router.push(scopedUrl(READING_HOME));
          }}
        />
      )}
    </FolderFrame>
  );
}

function FolderFrame({ children }: { children: React.ReactNode }) {
  return (
    <section className="h-full min-h-0 w-full overflow-y-auto bg-[var(--background)] text-[var(--foreground)]">
      <div className="mx-auto w-full max-w-[920px] px-6 py-7 md:px-9 lg:py-9">
        {children}
      </div>
    </section>
  );
}

function SectionHeading({ label, count }: { label: string; count: number }) {
  return (
    <h2 className="flex items-center gap-1.5 px-1 text-[11.5px] font-medium text-[var(--muted-foreground)]">
      {label}
      <span className="tabular-nums opacity-70">{count}</span>
    </h2>
  );
}

function FileRow({
  tab,
  opening,
  onOpen,
  onRemove,
}: {
  tab: ReadingWorkspaceTab;
  opening: boolean;
  onOpen: () => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const material = tab.material;
  const pending =
    material.status === "processing" || material.status === "queued";
  const failed = material.status === "failed";
  const detail = pending
    ? t("Preparing")
    : failed
      ? t("Could not prepare this file")
      : materialDetail(material);

  return (
    <li className="group flex items-center">
      <button
        type="button"
        onClick={onOpen}
        title={t("Open in reader")}
        className="flex min-w-0 flex-1 items-center gap-3 px-1 py-2.5 text-left transition hover:bg-[var(--secondary)]"
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-[var(--muted)] text-[var(--muted-foreground)]">
          {opening || pending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <MaterialGlyph material={material} size={14} />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">
            {material.title || material.filename}
          </span>
          {detail && (
            <span
              className={`block truncate text-[11px] ${
                failed
                  ? "text-[var(--destructive)]"
                  : "text-[var(--muted-foreground)]"
              }`}
            >
              {detail}
            </span>
          )}
        </span>
      </button>
      <button
        type="button"
        onClick={onRemove}
        aria-label={t("Remove from collection")}
        title={t("Remove from collection")}
        className="mx-1 flex size-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] opacity-100 transition hover:bg-[var(--muted)] hover:text-[var(--foreground)] sm:opacity-0 sm:focus:opacity-100 sm:group-hover:opacity-100"
      >
        <X size={13} />
      </button>
    </li>
  );
}
