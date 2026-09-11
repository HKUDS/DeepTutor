"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  FolderPlus,
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
  addReadingWorkspaceMaterial,
  deleteReadingMaterial,
  listReadingLibraryMaterials,
  listReadingWorkspaces,
  retryReadingMaterial,
  type ReadingLibraryCounts,
  type ReadingLibraryFilter,
  type ReadingLibraryMaterial,
  type ReadingWorkspace,
} from "@/lib/reading-workspace-api";
import { readingFailureMessage } from "@/lib/reading-failure";

import { AddMaterialsDialog } from "./AddMaterialsDialog";
import { LibraryShell } from "./LibraryShell";
import {
  displayUrl,
  formatBytes,
  formatDuration,
  formatTag,
  MaterialGlyph,
  relativeDate,
  sourceKindKey,
} from "./shared";

/**
 * Grid template shared by the header and every row, so columns line up.
 * Membership earns its column before the type does: "which collections is this
 * in, and what is in none of them" is the question this view exists to answer.
 */
const GRID =
  "grid grid-cols-[28px_minmax(0,1fr)_72px_28px] items-center gap-x-3 " +
  "sm:grid-cols-[32px_minmax(0,1fr)_minmax(0,200px)_72px_28px] " +
  "lg:grid-cols-[32px_minmax(0,1fr)_104px_minmax(0,236px)_72px_28px]";

export function MaterialLibraryPage() {
  const { t, i18n } = useTranslation();
  const [materials, setMaterials] = useState<ReadingLibraryMaterial[]>([]);
  const [counts, setCounts] = useState<ReadingLibraryCounts | null>(null);
  const [collections, setCollections] = useState<ReadingWorkspace[]>([]);
  const [filter, setFilter] = useState<ReadingLibraryFilter>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [assignFor, setAssignFor] = useState<ReadingLibraryMaterial | null>(
    null,
  );
  const [deleteFor, setDeleteFor] = useState<ReadingLibraryMaterial | null>(
    null,
  );

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [library, collectionRows] = await Promise.all([
        listReadingLibraryMaterials(search, filter),
        listReadingWorkspaces(),
      ]);
      setMaterials(library.materials);
      setCounts(library.counts);
      setCollections(collectionRows);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : t("Could not load your library."),
      );
    } finally {
      setLoading(false);
    }
  }, [filter, search, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 140);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  // Until the server reports totals, derive what we can from the rows on
  // screen so the filter chips are never blank.
  const tally = useMemo(() => {
    if (counts) return counts;
    return {
      all: materials.length,
      unassigned: materials.filter((row) => !(row.collections ?? []).length)
        .length,
      processing: materials.filter(
        (row) => row.status === "processing" || row.status === "queued",
      ).length,
      failed: materials.filter((row) => row.status === "failed").length,
      by_kind: {},
    } satisfies ReadingLibraryCounts;
  }, [counts, materials]);

  return (
    <LibraryShell
      view="materials"
      materialCount={tally.all}
      collectionCount={collections.length}
      actionLabel={t("Upload material")}
      onAction={() => setShowUpload(true)}
    >
      <div className="mt-5 flex flex-col gap-3 border-b border-[var(--border)] pb-3 sm:flex-row sm:items-center">
        <label className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-lg border border-[var(--border)] px-2.5 sm:max-w-[330px]">
          <Search
            size={13}
            className="shrink-0 text-[var(--muted-foreground)]"
          />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("Search by title, file name or link")}
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
        <span className="text-[11px] text-[var(--muted-foreground)] sm:ml-auto">
          {t("{{count}} materials", { count: tally.all })}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <FilterChip
          label={t("All")}
          active={filter === "all"}
          onClick={() => setFilter("all")}
        />
        <FilterChip
          label={t("Not in a collection")}
          count={tally.unassigned}
          active={filter === "unassigned"}
          onClick={() => setFilter("unassigned")}
        />
        <FilterChip
          label={t("Preparing")}
          count={tally.processing}
          active={filter === "processing"}
          onClick={() => setFilter("processing")}
        />
        <FilterChip
          label={t("Failed")}
          count={tally.failed}
          active={filter === "failed"}
          onClick={() => setFilter("failed")}
        />
      </div>

      {error && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2.5 text-[11.5px] text-[var(--destructive)]">
          <TriangleAlert size={13} />
          <span className="min-w-0 flex-1">{error}</span>
          <button
            type="button"
            onClick={() => void refresh()}
            className="shrink-0 font-semibold text-[var(--primary)]"
          >
            {t("Retry")}
          </button>
        </div>
      )}

      <div
        className={`${GRID} mt-5 border-b border-[var(--border)] pb-2 text-[10.5px] text-[var(--muted-foreground)]`}
      >
        <span />
        <span className="min-w-0">{t("reading.column.material")}</span>
        <span className="hidden min-w-0 lg:block">{t("Type")}</span>
        <span className="hidden min-w-0 sm:block">{t("In collections")}</span>
        <span className="text-right">{t("Added")}</span>
        <span />
      </div>

      {loading ? (
        <div className="flex min-h-[240px] items-center justify-center gap-2 text-[12px] text-[var(--muted-foreground)]">
          <Loader2 size={15} className="animate-spin" />
          {t("Loading…")}
        </div>
      ) : !materials.length ? (
        // Same rule as the collections view: an error already said what
        // happened, and "nothing here" would contradict it.
        error ? null : (
          <p className="py-16 text-center text-[12px] text-[var(--muted-foreground)]">
            {search
              ? t("Nothing matches that.")
              : filter === "all"
                ? t("Everything you upload shows up here.")
                : t("Nothing here yet.")}
          </p>
        )
      ) : (
        <ul>
          {materials.map((material) => (
            <MaterialRow
              key={material.material_id}
              material={material}
              locale={i18n.language}
              menuOpen={menuFor === material.material_id}
              onToggleMenu={() =>
                setMenuFor((current) =>
                  current === material.material_id
                    ? null
                    : material.material_id,
                )
              }
              onAssign={() => {
                setMenuFor(null);
                setAssignFor(material);
              }}
              onDelete={() => {
                setMenuFor(null);
                setDeleteFor(material);
              }}
              onRetried={() => void refresh()}
            />
          ))}
        </ul>
      )}

      {showUpload && (
        <AddMaterialsDialog
          mode="upload"
          onClose={() => setShowUpload(false)}
          onDone={() => {
            setShowUpload(false);
            void refresh();
          }}
        />
      )}

      {assignFor && (
        <AssignDialog
          material={assignFor}
          collections={collections}
          onClose={() => setAssignFor(null)}
          onAssigned={async () => {
            setAssignFor(null);
            await refresh();
          }}
        />
      )}

      {deleteFor && (
        <DeleteMaterialDialog
          material={deleteFor}
          onClose={() => setDeleteFor(null)}
          onDeleted={async () => {
            setDeleteFor(null);
            await refresh();
          }}
        />
      )}
    </LibraryShell>
  );
}

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition ${
        active
          ? "border-[var(--foreground)] bg-[var(--foreground)] text-[var(--background)]"
          : "border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      }`}
    >
      {label}
      {typeof count === "number" && count > 0 && (
        <span className="tabular-nums opacity-70">{count}</span>
      )}
    </button>
  );
}

function MaterialRow({
  material,
  locale,
  menuOpen,
  onToggleMenu,
  onAssign,
  onDelete,
  onRetried,
}: {
  material: ReadingLibraryMaterial;
  locale: string;
  menuOpen: boolean;
  onToggleMenu: () => void;
  onAssign: () => void;
  onDelete: () => void;
  onRetried: () => void;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const collections = material.collections ?? [];
  const tag = formatTag(material);
  const duration = formatDuration(material.duration_seconds);
  const size = formatBytes(material.size_bytes);
  // Pages for a paginated document, sections for everything else: the word
  // has to match what the reader will actually scroll through.
  const extent = material.unit_count
    ? material.render_mode === "pdf"
      ? t("{{count}} pages", { count: material.unit_count })
      : t("{{count}} sections", { count: material.unit_count })
    : "";
  const preparing =
    material.status === "processing" || material.status === "queued";
  const failed = material.status === "failed";

  // The file's own identity: what it is called on disk, or where it came from.
  const identity =
    material.source_kind === "web" ||
    material.source_kind === "youtube" ||
    material.source_kind === "bilibili"
      ? displayUrl(material.source_url)
      : material.filename;
  // What the file is called (or where it came from), plus its size. The type
  // facts follow only on narrow screens, where the type column is hidden.
  const secondary = [identity, size, extent].filter(Boolean).join(" · ");
  const typeTail = [tag, duration].filter(Boolean).join(" · ");

  const open = () => {
    const target = collections[0];
    if (target) router.push(`/reading/${target.workspace_id}`);
    else onAssign();
  };

  return (
    <li className="group relative border-b border-[var(--border)]">
      <div className={`${GRID} py-2.5`}>
        <button
          type="button"
          onClick={open}
          aria-label={material.title}
          className="flex size-8 items-center justify-center rounded-lg bg-[var(--muted)] text-[var(--muted-foreground)]"
        >
          {preparing ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <MaterialGlyph material={material} />
          )}
        </button>

        <button type="button" onClick={open} className="min-w-0 text-left">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="min-w-0 truncate text-[12.5px] font-medium">
              {material.title}
            </span>
            {preparing && (
              <span className="shrink-0 rounded px-1.5 py-px text-[10px] text-[var(--primary)]">
                {material.progress}%
              </span>
            )}
            {failed && (
              <span className="shrink-0 rounded px-1.5 py-px text-[10px] text-[var(--destructive)]">
                {t("Failed")}
              </span>
            )}
          </span>
          {/* Narrow screens lose the type and collection columns, so those
              facts lead the second line: they are short and certain, while the
              file name is the part that can afford to be cut. */}
          <span className="mt-0.5 flex min-w-0 items-baseline gap-1 text-[10.5px] text-[var(--muted-foreground)]">
            {!!typeTail && !failed && (
              <span className="shrink-0 lg:hidden">{typeTail} ·</span>
            )}
            {!failed && (
              <span className="hidden max-w-[45%] shrink-0 truncate sm:hidden min-[420px]:inline">
                {collections.length
                  ? collections.map((row) => row.title).join("、")
                  : t("Not in a collection")}{" "}
                ·
              </span>
            )}
            <span className="min-w-0 truncate">
              {failed && readingFailureMessage(material, t)
                ? readingFailureMessage(material, t)
                : secondary}
            </span>
          </span>
        </button>

        <span className="hidden min-w-0 truncate text-[11px] text-[var(--muted-foreground)] lg:block">
          {[tag || t(sourceKindKey[material.source_kind]), duration || extent]
            .filter(Boolean)
            .join(" · ")}
        </span>

        <span className="hidden min-w-0 items-center gap-1 sm:flex">
          {collections.length ? (
            <>
              {/* The first chip takes the room the second one leaves, so a
                  single membership reads in full and two share the column. */}
              {collections.slice(0, 2).map((row, index) => (
                <Link
                  key={row.workspace_id}
                  href={`/reading/${row.workspace_id}`}
                  className={`min-w-0 truncate rounded-full border border-[var(--border)] px-2 py-0.5 text-[10.5px] hover:border-[var(--primary)] hover:text-[var(--primary)] ${
                    index === 0 ? "flex-1" : "max-w-[96px] shrink-0"
                  }`}
                >
                  {row.title}
                </Link>
              ))}
              {collections.length > 2 && (
                <span className="shrink-0 text-[10.5px] text-[var(--muted-foreground)]">
                  +{collections.length - 2}
                </span>
              )}
            </>
          ) : (
            <button
              type="button"
              onClick={onAssign}
              className="flex items-center gap-1 rounded-full border border-dashed border-[var(--border)] px-2 py-0.5 text-[10.5px] text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--primary)]"
            >
              <FolderPlus size={10} />
              {t("Add to a collection")}
            </button>
          )}
        </span>

        <span className="text-right text-[10.5px] text-[var(--muted-foreground)]">
          {failed ? (
            <button
              type="button"
              onClick={() => {
                void retryReadingMaterial(material.material_id)
                  .then(onRetried)
                  .catch(() => undefined);
              }}
              className="font-semibold text-[var(--primary)]"
            >
              {t("Retry")}
            </button>
          ) : (
            relativeDate(material.created_at, locale)
          )}
        </span>

        <button
          type="button"
          onClick={onToggleMenu}
          aria-label={t("Material menu")}
          className="flex size-7 items-center justify-center rounded-md text-[var(--muted-foreground)] opacity-100 transition hover:bg-[var(--muted)] sm:opacity-0 sm:group-hover:opacity-100 sm:focus:opacity-100"
        >
          <MoreHorizontal size={14} />
        </button>
      </div>

      {menuOpen && (
        <div className="absolute right-1 top-[calc(100%-8px)] z-10 w-44 rounded-lg border border-[var(--border)] bg-[var(--card)] p-1 text-[11.5px] shadow-md dark:bg-[var(--popover)]">
          <button
            type="button"
            onClick={onAssign}
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left hover:bg-[var(--muted)]"
          >
            <FolderPlus size={12} />
            {t("Add to a collection")}
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-[var(--destructive)] hover:bg-[var(--muted)]"
          >
            <Trash2 size={12} />
            {t("Delete material")}
          </button>
        </div>
      )}
    </li>
  );
}

function AssignDialog({
  material,
  collections,
  onClose,
  onAssigned,
}: {
  material: ReadingLibraryMaterial;
  collections: ReadingWorkspace[];
  onClose: () => void;
  onAssigned: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const held = new Set(
    (material.collections ?? []).map((row) => row.workspace_id),
  );
  const available = collections.filter(
    (collection) => !held.has(collection.workspace_id),
  );

  if (creating) {
    return (
      <AddMaterialsDialog
        mode="create"
        onClose={() => setCreating(false)}
        onDone={({ workspace }) => {
          if (!workspace) {
            setCreating(false);
            return;
          }
          void addReadingWorkspaceMaterial(
            workspace.workspace_id,
            material.material_id,
            true,
          )
            .then(() => router.push(`/reading/${workspace.workspace_id}`))
            .catch(() => setCreating(false));
        }}
      />
    );
  }

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-[var(--overlay)] p-4">
      <div className="flex max-h-[80vh] w-full max-w-md flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-lg dark:bg-[var(--popover)]">
        <div className="border-b border-[var(--border)] px-5 py-4">
          <h2 className="font-serif text-[17px] font-semibold">
            {t("Add to a collection")}
          </h2>
          <p className="mt-1 truncate text-[11px] text-[var(--muted-foreground)]">
            {material.title}
          </p>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {available.length ? (
            available.map((collection) => (
              <button
                key={collection.workspace_id}
                type="button"
                disabled={Boolean(working)}
                onClick={() => {
                  setWorking(collection.workspace_id);
                  setError("");
                  void addReadingWorkspaceMaterial(
                    collection.workspace_id,
                    material.material_id,
                    true,
                  )
                    .then(onAssigned)
                    .catch((caught) =>
                      setError(
                        caught instanceof Error
                          ? caught.message
                          : t("Save failed."),
                      ),
                    )
                    .finally(() => setWorking(""));
                }}
                className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left hover:bg-[var(--muted)] disabled:opacity-60"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-serif text-[13px] font-semibold">
                    {collection.title}
                  </span>
                  <span className="block truncate text-[10.5px] text-[var(--muted-foreground)]">
                    {t("{{count}} materials", {
                      count: collection.tabs.length,
                    })}
                  </span>
                </span>
                {working === collection.workspace_id && (
                  <Loader2 size={13} className="animate-spin" />
                )}
              </button>
            ))
          ) : (
            <p className="px-3 py-6 text-center text-[11.5px] text-[var(--muted-foreground)]">
              {collections.length
                ? t("It is already in every collection you have.")
                : t("You have no collections yet.")}
            </p>
          )}
        </div>
        {error && (
          <p className="px-5 pb-1 text-[11px] text-[var(--destructive)]">
            {error}
          </p>
        )}
        <div className="flex items-center justify-between gap-2 border-t border-[var(--border)] px-5 py-3.5">
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="text-[11.5px] font-semibold text-[var(--primary)]"
          >
            {t("New collection…")}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="h-8 rounded-lg px-3 text-[11.5px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            {t("Cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}

function DeleteMaterialDialog({
  material,
  onClose,
  onDeleted,
}: {
  material: ReadingLibraryMaterial;
  onClose: () => void;
  onDeleted: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const collections = material.collections ?? [];

  return (
    <div className="fixed inset-0 z-[110] flex items-center justify-center bg-[var(--overlay)] p-4">
      <div className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-lg dark:bg-[var(--popover)]">
        <h2 className="font-serif text-[17px] font-semibold">
          {t("Delete material")}
        </h2>
        <p className="mt-2 text-[12px] leading-relaxed text-[var(--muted-foreground)]">
          {collections.length
            ? t(
                "“{{title}}” is used by {{where}}. Deleting it removes it from those collections, along with its annotations.",
                {
                  title: material.title,
                  where: collections.map((row) => row.title).join("、"),
                },
              )
            : t("“{{title}}” and its annotations will be deleted.", {
                title: material.title,
              })}
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
              void deleteReadingMaterial(material.material_id)
                .then(onDeleted)
                .catch((caught) =>
                  setError(
                    caught instanceof Error
                      ? caught.message
                      : t("Delete failed"),
                  ),
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
