"use client";

import { learningLibrary, libraryItemKey } from "@/lib/learning-library";
import { activeWorkspaceId } from "@/lib/workspace-scope";
import { useLearningCreation, requestedLearningCreation, useLibraryFilter, WorkspaceLabel } from "@/components/learning/LibraryWorkspace";
import { LearningCardContent } from "@/components/learning/LearningCard";

import {
  LearningEmptyState,
  LearningErrorState,
  LearningSkeleton,
} from "@/components/learning/LearningShell";

import { readingCollectionRoute } from "@/lib/learning-routes";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ChevronRight,
  Loader2,
  MoreHorizontal,
  Search,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  deleteReadingWorkspace,
  retryReadingMaterial,
  type ReadingLibraryMaterial,
  type ReadingWorkspace,
} from "@/lib/reading-workspace-api";
import { readingFailureMessage } from "@/lib/reading-failure";

import {
  CourseScopeChip,
  useCourseScope,
} from "@/components/courses/CourseScope";

import { AddMaterialsDialog } from "./AddMaterialsDialog";
import { LibraryShell } from "./LibraryShell";
import { MaterialGlyph } from "./shared";

type SortMode = "recent" | "name";

export function ReadingLibraryPage() {
  const { t, i18n } = useTranslation();
  const router = useRouter();
  const [allCollections, setCollections] = useState<ReadingWorkspace[]>([]);
  const [materials, setMaterials] = useState<ReadingLibraryMaterial[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("recent");
  const [showAdd, setShowAdd] = useState(requestedLearningCreation);
  const creation = useLearningCreation(() => setShowAdd(true));
  const { rows: collections, control } = useLibraryFilter(allCollections);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ReadingWorkspace | null>(
    null
  );

  // Present when opened from a course page or a Course Study hand-off.
  const scope = useCourseScope();

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [collectionRows, library] = await Promise.all([
        learningLibrary<ReadingWorkspace>("reading"),
        learningLibrary<ReadingLibraryMaterial>("materials"),
      ]);
      setCollections(collectionRows.items.filter(row => !search || `${row.title} ${row.description}`.toLowerCase().includes(search.toLowerCase())));
      setMaterials(library.items);
      if (collectionRows.unavailable_workspaces.length || library.unavailable_workspaces.length) setError(t("Some workspaces could not be loaded. Available content is shown."));
    } catch (caught) {
      // Keep whatever is on screen: an empty list would claim the user has no
      // collections, which is a different statement from "the request failed".
      setError(
        caught instanceof Error
          ? caught.message
          : t("Could not load your collections.")
      );
    } finally {
      setLoading(false);
    }
  }, [search, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 140);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  // Materials still being prepared, or that failed — the list page is where a
  // user looks first, so it has to say so here rather than only inside a
  // collection.
  const unsettled = useMemo(
    () =>
      materials.filter(
        material =>
          material.status === "processing" ||
          material.status === "queued" ||
          material.status === "failed"
      ),
    [materials]
  );

  // Opened inside a course, this is that course's shelf: only the collections
  // it references, and anything made here joins it. A course that references
  // none shows the empty pitch, which is now a real offer rather than a dead
  // end — creating from it attaches on the way out.
  const rows = useMemo(() => {
    const allowed = scope ? new Set(scope.refIds("reading_workspace")) : null;
    const sorted = collections.filter(
      collection => !allowed || (allowed.has(collection.workspace_id) && (collection.content_workspace_id ?? "") === activeWorkspaceId())
    );
    sorted.sort((a, b) =>
      sort === "name"
        ? a.title.localeCompare(b.title, i18n.language)
        : b.updated_at - a.updated_at
    );
    return sorted;
  }, [collections, i18n.language, scope, sort]);

  return (
    <LibraryShell
      view="collections"
      collectionCount={rows.length}
      materialCount={materials.length}
      actionLabel={t("New collection")}
      onAction={creation.begin}
      scopeChip={scope ? <CourseScopeChip scope={scope} /> : null}
    >
      {creation.dialog}
      {control}
      <div className="mt-5 flex flex-col gap-3 border-b border-[var(--border)] pb-3 sm:flex-row sm:items-center">
        <label className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-lg border border-[var(--border)] px-2.5 sm:max-w-[330px]">
          <Search
            size={13}
            className="shrink-0 text-[var(--muted-foreground)]"
          />
          <input
            value={search}
            onChange={event => setSearch(event.target.value)}
            placeholder={t("Search collections and materials")}
            className="min-w-0 flex-1 bg-transparent text-[12px] outline-none placeholder:text-[var(--muted-foreground)]"
          />
          {!!search && (
            <button
              type="button"
              onClick={() => setSearch("")}
              aria-label={t("Clear")}
            >
              <X size={12} className="text-[var(--muted-foreground)]" />
            </button>
          )}
        </label>
        <div className="flex items-center gap-2 sm:ml-auto">
          <span className="text-[11px] text-[var(--muted-foreground)]">
            {t("{{count}} collections", { count: rows.length })}
          </span>
          <div className="flex overflow-hidden rounded-md border border-[var(--border)]">
            <SortButton
              label={t("Recent")}
              active={sort === "recent"}
              onClick={() => setSort("recent")}
            />
            <SortButton
              label={t("Name")}
              active={sort === "name"}
              onClick={() => setSort("name")}
            />
          </div>
        </div>
      </div>

      {error && (
        <LearningErrorState message={error} onRetry={() => void refresh()} />
      )}

      {unsettled.map(material => (
        <UnsettledRow
          key={libraryItemKey(material, material.material_id)}
          material={material}
          onRetried={() => void refresh()}
        />
      ))}

      {loading ? (
        <LearningSkeleton />
      ) : !rows.length ? (
        // A failed request is not an empty library: showing the "no
        // collections yet" pitch on top of an error would state something we
        // do not know to be true.
        error ? null : (
          <EmptyCollections
            searching={Boolean(search)}
            onCreate={creation.begin}
          />
        )
      ) : (
        <ul className="mt-1">
          {rows.map(collection => (
            <CollectionRow
              key={libraryItemKey(collection, collection.workspace_id)}
              collection={collection}
              menuOpen={menuFor === libraryItemKey(collection, collection.workspace_id)}
              onToggleMenu={() =>
                setMenuFor(current =>
                  current === libraryItemKey(collection, collection.workspace_id)
                    ? null
                    : libraryItemKey(collection, collection.workspace_id)
                )
              }
              onDelete={() => {
                setMenuFor(null);
                setDeleteTarget(collection);
              }}
            />
          ))}
        </ul>
      )}

      {showAdd && (
        <AddMaterialsDialog
          mode="create"
          onClose={() => setShowAdd(false)}
          onDone={async ({ workspace }) => {
            setShowAdd(false);
            if (workspace) {
              await scope?.attach(
                "reading_workspace",
                workspace.workspace_id,
                workspace.title
              );
              router.push(readingCollectionRoute(workspace.workspace_id));
            } else void refresh();
          }}
        />
      )}

      {deleteTarget && (
        <DeleteCollectionDialog
          collection={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={async () => {
            setDeleteTarget(null);
            await refresh();
          }}
        />
      )}
    </LibraryShell>
  );
}

function SortButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-2.5 py-1 text-[11px] transition ${
        active
          ? "bg-[var(--muted)] font-semibold text-[var(--foreground)]"
          : "text-[var(--muted-foreground)]"
      }`}
    >
      {label}
    </button>
  );
}

function CollectionRow({
  collection,
  menuOpen,
  onToggleMenu,
  onDelete,
}: {
  collection: ReadingWorkspace;
  menuOpen: boolean;
  onToggleMenu: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const first = collection.tabs[0]?.material;
  const names = collection.tabs.slice(0, 2).map(tab => tab.material.title);
  const rest = collection.tabs.length - names.length;
  const preparing = collection.tabs.some(
    tab =>
      tab.material.status === "processing" || tab.material.status === "queued"
  );

  return (
    <li className="group relative my-3 rounded-xl border border-[var(--border)]">
      <WorkspaceLabel row={collection} />
      <Link
        href={readingCollectionRoute(collection.workspace_id, collection.content_workspace_id ?? "")}
        className="flex items-center gap-3 rounded-xl py-4 pl-4 pr-10 transition hover:bg-[var(--secondary)]"
      >
        <LearningCardContent
          title={collection.title}
          icon={
            preparing ? (
              <Loader2 size={14} className="animate-spin" />
            ) : first ? (
              <MaterialGlyph material={first} />
            ) : (
              <ChevronRight size={14} />
            )
          }
          subtitle={
            names.length
              ? [
                  names.join(" · "),
                  rest > 0 ? t("+{{count}} more", { count: rest }) : "",
                ]
                  .filter(Boolean)
                  .join(" · ")
              : t("No material yet")
          }
          updatedAt={collection.updated_at}
        />
      </Link>
      <button
        type="button"
        onClick={onToggleMenu}
        aria-label={t("Collection menu")}
        className="absolute right-1 top-1/2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-[var(--muted-foreground)] opacity-100 transition hover:bg-[var(--muted)] sm:opacity-0 sm:group-hover:opacity-100 sm:focus:opacity-100"
      >
        <MoreHorizontal size={14} />
      </button>
      {menuOpen && (
        <div className="absolute right-1 top-[calc(50%+14px)] z-10 w-40 rounded-lg border border-[var(--border)] bg-[var(--card)] p-1 text-[11.5px] shadow-md dark:bg-[var(--popover)]">
          <button
            type="button"
            onClick={onDelete}
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-[var(--destructive)] hover:bg-[var(--muted)]"
          >
            <Trash2 size={12} />
            {t("Delete collection")}
          </button>
        </div>
      )}
    </li>
  );
}

function UnsettledRow({
  material,
  onRetried,
}: {
  material: ReadingLibraryMaterial;
  onRetried: () => void;
}) {
  const { t } = useTranslation();
  const [retrying, setRetrying] = useState(false);
  const failed = material.status === "failed";

  return (
    <div className="mt-3 flex items-center gap-3 rounded-lg border border-[var(--border)] px-3 py-2.5">
      {failed ? (
        <TriangleAlert
          size={13}
          className="shrink-0 text-[var(--destructive)]"
        />
      ) : (
        <Loader2
          size={13}
          className="shrink-0 animate-spin text-[var(--primary)]"
        />
      )}
      <span className="min-w-0 flex-1 truncate text-[11.5px]">
        {failed
          ? t("{{title}} could not be prepared", { title: material.title })
          : t("Preparing {{title}}", { title: material.title })}
        {failed && readingFailureMessage(material, t) ? (
          <span className="ml-1.5 text-[10.5px] text-[var(--muted-foreground)]">
            {readingFailureMessage(material, t)}
          </span>
        ) : null}
      </span>
      {!failed && (
        <>
          <span className="hidden h-[3px] w-[160px] shrink-0 overflow-hidden rounded-full bg-[var(--muted)] sm:block">
            <span
              className="block h-full bg-[var(--primary)]"
              style={{ width: `${Math.max(4, material.progress)}%` }}
            />
          </span>
          <span className="shrink-0 text-[10.5px] tabular-nums text-[var(--muted-foreground)]">
            {material.progress}%
          </span>
        </>
      )}
      {failed && (
        <button
          type="button"
          disabled={retrying}
          onClick={() => {
            setRetrying(true);
            void retryReadingMaterial(material.material_id, material.content_workspace_id ?? "")
              .then(onRetried)
              .catch(() => undefined)
              .finally(() => setRetrying(false));
          }}
          className="shrink-0 text-[11px] font-semibold text-[var(--primary)] disabled:opacity-50"
        >
          {retrying ? t("Retrying…") : t("Retry")}
        </button>
      )}
    </div>
  );
}

function EmptyCollections({
  searching,
  onCreate,
}: {
  searching: boolean;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  return (
    <LearningEmptyState
      title={searching ? t("Nothing matches that.") : t("No collections yet")}
      description={
        !searching &&
        t(
          "A collection is one reading task: a paper with its survey, every lecture of a course, a few chapters of a book. Everything in it shares the same conversations and annotations."
        )
      }
      action={
        !searching && (
          <button
            type="button"
            onClick={onCreate}
            className="inline-flex h-8 items-center rounded-lg bg-[var(--primary)] px-3.5 text-xs font-semibold text-[var(--primary-foreground)]"
          >
            {t("New collection")}
          </button>
        )
      }
    />
  );
}

function DeleteCollectionDialog({
  collection,
  onClose,
  onDeleted,
}: {
  collection: ReadingWorkspace;
  onClose: () => void;
  onDeleted: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-[var(--overlay)] p-4">
      <div className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-lg dark:bg-[var(--popover)]">
        <h2 className="font-serif text-[17px] font-semibold">
          {t("Delete collection")}
        </h2>
        <p className="mt-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
          {t(
            "“{{title}}” and its reading conversations will be deleted. The {{count}} materials in it stay in your library.",
            {
              title: collection.title,
              count: collection.tabs.length,
            }
          )}
        </p>
        {error && (
          <p className="mt-3 text-[11px] text-[var(--destructive)]">{error}</p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="h-8 rounded-lg px-3 text-[11.5px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            {t("Cancel")}
          </button>
          <button
            type="button"
            disabled={working}
            onClick={() => {
              setWorking(true);
              setError("");
              void deleteReadingWorkspace(collection.workspace_id, collection.content_workspace_id ?? "")
                .then(onDeleted)
                .catch(caught =>
                  setError(
                    caught instanceof Error
                      ? caught.message
                      : t("Delete failed")
                  )
                )
                .finally(() => setWorking(false));
            }}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--destructive)] px-3.5 text-[11.5px] font-semibold text-[var(--destructive-foreground)] disabled:opacity-50"
          >
            {working && <Loader2 size={12} className="animate-spin" />}
            {t("Delete")}
          </button>
        </div>
      </div>
    </div>
  );
}
