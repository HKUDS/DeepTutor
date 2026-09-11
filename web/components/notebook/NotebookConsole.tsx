"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Download,
  Loader2,
  NotebookPen,
  Pencil,
  Plus,
  School,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import Tooltip from "@/components/common/Tooltip";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import NotebookRecordRow from "@/components/notebook/NotebookRecordRow";
import { useNotebookLibrary } from "@/components/notebook/useNotebookLibrary";
import { attachCourseResource } from "@/lib/courses-api";
import { notify } from "@/lib/notifications";
import { exportNotebookMarkdown } from "@/lib/notebook-api";
import { notebookRoute } from "@/lib/resource-routes";

const SWATCHES = [
  "#6366F1",
  "#3B82F6",
  "#10B981",
  "#F59E0B",
  "#EF4444",
  "#8B5CF6",
  "#64748B",
];

/** The course this visit is scoped to, resolved by the route. */
export interface NotebookCourseScope {
  id: string;
  /** Empty when the course could not be read; the chip then says "this course". */
  name: string;
  /** Notebooks the course references. Empty means the course has none. */
  notebookIds: string[];
}

interface NotebookConsoleProps {
  /** Notebook to open on arrival from `/notebooks/<id>`. */
  initialNotebookId?: string | null;
  /** Present when arriving from a course; narrows the library to its notebooks. */
  courseScope?: NotebookCourseScope | null;
  /** Called after this console attaches something to the course, so the route can re-read it. */
  onScopeChanged?: () => void;
}

export default function NotebookConsole({
  initialNotebookId,
  courseScope = null,
  onScopeChanged,
}: NotebookConsoleProps) {
  const { t } = useTranslation();
  const router = useRouter();
  const library = useNotebookLibrary(
    initialNotebookId,
    courseScope?.notebookIds ?? null,
  );

  const [notebookQuery, setNotebookQuery] = useState("");
  const [recordQuery, setRecordQuery] = useState("");
  const [expandedRecordId, setExpandedRecordId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [editingMeta, setEditingMeta] = useState(false);
  const [metaName, setMetaName] = useState("");
  const [metaDescription, setMetaDescription] = useState("");
  const [metaColor, setMetaColor] = useState(SWATCHES[0]);
  const [banner, setBanner] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const { notebooks, selected, selectedId } = library;
  const courseId = courseScope?.id ?? null;

  // Default selection, scope repair, create, and delete can all change the
  // visible resource without a click. Keep the address bar canonical too.
  useEffect(() => {
    if (!selectedId || selectedId === initialNotebookId) return;
    router.replace(notebookRoute(selectedId, courseId));
  }, [courseId, initialNotebookId, router, selectedId]);

  // How many notebooks exist *for this visit*. Everything the console counts —
  // the badge, whether a filter box is worth showing, which empty state to use
  // — reads this rather than the whole library, or a course-scoped visit would
  // report numbers the list does not back up.
  const scopedNotebooks = useMemo(
    () =>
      courseScope
        ? notebooks.filter((notebook) =>
            courseScope.notebookIds.includes(notebook.id),
          )
        : notebooks,
    [courseScope, notebooks],
  );

  const visibleNotebooks = useMemo(() => {
    const needle = notebookQuery.trim().toLowerCase();
    if (!needle) return scopedNotebooks;
    return scopedNotebooks.filter((notebook) =>
      `${notebook.name} ${notebook.description ?? ""}`
        .toLowerCase()
        .includes(needle),
    );
  }, [scopedNotebooks, notebookQuery]);

  // The library opens the most recent notebook by default, which under a course
  // scope can be one the course does not reference — the list then shows one
  // notebook while the pane beside it shows another. Pull the selection back
  // inside the scope, and when the scope is empty clear it outright: a course
  // with no notebooks must not leave some other course's notes on screen next
  // to a list that says there are none.
  const scopedSelect = library.select;
  useEffect(() => {
    if (!courseScope) return;
    if (selectedId && courseScope.notebookIds.includes(selectedId)) return;
    scopedSelect(scopedNotebooks.length ? scopedNotebooks[0].id : null);
  }, [courseScope, scopedNotebooks, scopedSelect, selectedId]);

  const visibleRecords = useMemo(() => {
    const records = selected?.records ?? [];
    const needle = recordQuery.trim().toLowerCase();
    if (!needle) return records;
    return records.filter((record) =>
      `${record.title} ${record.summary ?? ""} ${record.output ?? ""}`
        .toLowerCase()
        .includes(needle),
    );
  }, [selected, recordQuery]);

  const handleCreate = useCallback(async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      const createdId = await library.create(name, newDescription);
      // Made while looking at one course, so it belongs to that course. Asking
      // the learner to go back and attach what they just created inside the
      // course's own view is the busywork the container exists to remove.
      if (createdId && courseScope) {
        await attachCourseResource(courseScope.id, {
          kind: "notebook",
          ref_id: createdId,
          label: name,
        });
        onScopeChanged?.();
      }
      if (createdId) router.push(notebookRoute(createdId, courseId));
      setNewName("");
      setNewDescription("");
      setCreating(false);
    } catch (err) {
      setBanner(err instanceof Error ? err.message : String(err));
    }
  }, [
    courseId,
    courseScope,
    library,
    newName,
    newDescription,
    onScopeChanged,
    router,
  ]);

  const beginMetaEdit = useCallback(() => {
    if (!selected) return;
    setMetaName(selected.name);
    setMetaDescription(selected.description ?? "");
    setMetaColor(selected.color ?? SWATCHES[0]);
    setEditingMeta(true);
  }, [selected]);

  const saveMeta = useCallback(async () => {
    if (!selectedId || !metaName.trim()) return;
    try {
      await library.rename(selectedId, {
        name: metaName.trim(),
        description: metaDescription.trim(),
        color: metaColor,
      });
      setEditingMeta(false);
    } catch (err) {
      setBanner(err instanceof Error ? err.message : String(err));
    }
  }, [library, selectedId, metaName, metaDescription, metaColor]);

  const handleDeleteNotebook = useCallback(async () => {
    if (!selected) return;
    const name = selected.name;
    setDeleting(true);
    try {
      await library.remove(selected.id);
      router.replace(notebookRoute(null, courseId));
      notify(t('Deleted "{{name}}"', { name }), { tone: "success" });
      setConfirmingDelete(false);
    } catch (err) {
      setBanner(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(false);
    }
  }, [courseId, library, router, selected, t]);

  const handleExport = useCallback(async () => {
    if (!selected) return;
    try {
      const markdown = await exportNotebookMarkdown(selected.id);
      const blob = new Blob([markdown], {
        type: "text/markdown;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${selected.name || selected.id}.md`;
      anchor.click();
      URL.revokeObjectURL(url);
      notify(t("Notebook exported"), { tone: "success" });
    } catch (err) {
      setBanner(err instanceof Error ? err.message : String(err));
    }
  }, [selected, t]);

  const openSession = useCallback(
    (sessionId: string) => {
      router.push(`/chat/${encodeURIComponent(sessionId)}`);
    },
    [router],
  );

  if (library.loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 bg-[var(--background)]">
      {/* ── Notebook rail ─────────────────────────────────── */}
      <aside className="flex w-[250px] shrink-0 flex-col border-r border-[var(--border)]">
        <div className="flex flex-col gap-2.5 px-3 pb-2.5 pt-3">
          <Link
            href="/space"
            className="group inline-flex w-fit items-center gap-1.5 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <ArrowLeft
              size={13}
              strokeWidth={1.8}
              className="transition-transform group-hover:-translate-x-0.5"
            />
            {t("Learning Space")}
          </Link>

          <div className="flex items-center justify-between">
            <h1 className="flex items-center gap-1.5 font-serif text-[15px] font-semibold tracking-tight text-[var(--foreground)]">
              <NotebookPen size={14} strokeWidth={1.7} />
              {t("Notebooks")}
              <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-normal tabular-nums text-[var(--muted-foreground)]">
                {scopedNotebooks.length}
              </span>
            </h1>
            <button
              type="button"
              onClick={() => setCreating((v) => !v)}
              title={t("New notebook")}
              aria-expanded={creating}
              className="rounded-md p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              <Plus size={15} />
            </button>
          </div>

          {creating && (
            <div className="flex flex-col gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] p-2">
              <input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleCreate();
                  if (e.key === "Escape") setCreating(false);
                }}
                placeholder={t("Notebook name")}
                className="rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-[12.5px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/50"
              />
              <input
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleCreate();
                  if (e.key === "Escape") setCreating(false);
                }}
                placeholder={t("Description (optional)")}
                className="rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-[12px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/50"
              />
              <div className="flex gap-1.5">
                <button
                  type="button"
                  onClick={() => void handleCreate()}
                  disabled={!newName.trim()}
                  className="flex-1 rounded-md bg-[var(--primary)] px-2 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
                >
                  {t("Create")}
                </button>
                <button
                  type="button"
                  onClick={() => setCreating(false)}
                  className="rounded-md border border-[var(--border)] px-2 py-1.5 text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                >
                  {t("Cancel")}
                </button>
              </div>
            </div>
          )}

          {courseScope ? (
            <div className="flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] py-1 pl-2 pr-1 text-[11px] text-[var(--muted-foreground)]">
              <School size={11} strokeWidth={1.8} className="shrink-0" />
              <Link
                href={`/courses/${courseScope.id}`}
                className="min-w-0 flex-1 truncate transition-colors hover:text-[var(--foreground)]"
              >
                {courseScope.name || t("This course")}
              </Link>
              <Link
                href="/notebooks"
                aria-label={t("Show every notebook")}
                className="shrink-0 rounded p-0.5 transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <X size={11} />
              </Link>
            </div>
          ) : null}

          {scopedNotebooks.length > 6 && (
            <div className="relative">
              <Search
                size={12}
                className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
              />
              <input
                value={notebookQuery}
                onChange={(e) => setNotebookQuery(e.target.value)}
                placeholder={t("Filter notebooks")}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--background)] py-1.5 pl-7 pr-2 text-[12px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/50"
              />
            </div>
          )}
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {visibleNotebooks.map((notebook) => {
            const active = selectedId === notebook.id;
            return (
              <button
                key={notebook.id}
                type="button"
                onClick={() => {
                  library.select(notebook.id);
                  router.push(notebookRoute(notebook.id, courseId));
                }}
                aria-current={active ? "true" : undefined}
                className={`group/nb relative mb-0.5 flex w-full items-start gap-2 rounded-lg py-2 pl-3 pr-2 text-left transition-[background-color,color] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40 ${
                  active
                    ? "bg-[var(--primary)]/10"
                    : "hover:bg-[var(--muted)]/50"
                }`}
              >
                {/* A left rail on the active row: the dot alone carries the
                    notebook's colour, not its selected state. */}
                <span
                  aria-hidden
                  className={`absolute left-0 top-1/2 w-[2.5px] -translate-y-1/2 rounded-r-full bg-[var(--primary)] transition-all duration-200 ${
                    active ? "h-[62%] opacity-100" : "h-0 opacity-0"
                  }`}
                />
                <span
                  aria-hidden
                  className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: notebook.color || "#6366F1" }}
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span
                      className={`min-w-0 flex-1 truncate text-[12.5px] ${active ? "font-semibold text-[var(--foreground)]" : "font-medium text-[var(--foreground)]/85"}`}
                    >
                      {notebook.name}
                    </span>
                    {notebook.unreadable ? (
                      <AlertTriangle
                        size={11}
                        className="shrink-0 text-[var(--destructive)]"
                      />
                    ) : (
                      <span className="shrink-0 text-[10.5px] tabular-nums text-[var(--muted-foreground)]">
                        {notebook.record_count ?? 0}
                      </span>
                    )}
                  </span>
                  {notebook.description && (
                    <span className="mt-0.5 block truncate text-[11px] text-[var(--muted-foreground)]">
                      {notebook.description}
                    </span>
                  )}
                </span>
              </button>
            );
          })}

          {!visibleNotebooks.length && (
            <p
              data-test="notebooks-empty"
              className="px-2 py-8 text-center text-[12px] text-[var(--muted-foreground)]"
            >
              {scopedNotebooks.length
                ? t("No notebooks match your filter.")
                : t("No notebooks yet.")}
            </p>
          )}
        </nav>
      </aside>

      {/* ── Records ───────────────────────────────────────── */}
      <section className="flex min-w-0 flex-1 flex-col">
        {banner && (
          <div
            role="alert"
            className="flex items-center gap-2 border-b border-[var(--destructive)]/30 bg-[var(--destructive)]/10 px-4 py-2 text-[12px] text-[var(--destructive)]"
          >
            <AlertTriangle size={13} />
            <span className="flex-1">{banner}</span>
            <button type="button" onClick={() => setBanner(null)}>
              <X size={13} />
            </button>
          </div>
        )}

        {library.error ? (
          <ConsoleNotice
            tone="error"
            title={t("Could not load your notebooks")}
            detail={library.error}
            action={
              <button
                type="button"
                onClick={() => void library.reload()}
                className="rounded-lg bg-[var(--primary)] px-3.5 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)]"
              >
                {t("Retry")}
              </button>
            }
          />
        ) : !selected && !library.detailLoading ? (
          <ConsoleNotice
            tone="empty"
            title={
              library.detailError
                ? t("This notebook could not be opened")
                : courseScope && scopedNotebooks.length === 0
                  ? t("This course has no notebook yet")
                  : t("No notebook selected")
            }
            detail={
              library.detailError ??
              (courseScope && scopedNotebooks.length === 0
                ? t(
                    "Make one here and it joins this course — its notes then travel with everything else in it.",
                  )
                : t(
                    "Pick a notebook on the left, or create one to get started.",
                  ))
            }
          />
        ) : (
          <>
            <header className="flex shrink-0 flex-col gap-2 border-b border-[var(--border)] px-4 py-3">
              {editingMeta ? (
                <div className="flex flex-col gap-2">
                  <input
                    autoFocus
                    value={metaName}
                    onChange={(e) => setMetaName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void saveMeta();
                      if (e.key === "Escape") setEditingMeta(false);
                    }}
                    placeholder={t("Notebook name")}
                    className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[14px] font-semibold text-[var(--foreground)] outline-none focus:border-[var(--primary)]/50"
                  />
                  <input
                    value={metaDescription}
                    onChange={(e) => setMetaDescription(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void saveMeta();
                      if (e.key === "Escape") setEditingMeta(false);
                    }}
                    placeholder={t("Description (optional)")}
                    className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[12.5px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/50"
                  />
                  <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1">
                      {SWATCHES.map((swatch) => (
                        <button
                          key={swatch}
                          type="button"
                          onClick={() => setMetaColor(swatch)}
                          aria-label={swatch}
                          className={`h-4 w-4 rounded-full transition-transform ${metaColor === swatch ? "ring-2 ring-[var(--foreground)]/40 ring-offset-1 ring-offset-[var(--background)]" : "hover:scale-110"}`}
                          style={{ backgroundColor: swatch }}
                        />
                      ))}
                    </div>
                    <button
                      type="button"
                      onClick={() => void saveMeta()}
                      disabled={!metaName.trim()}
                      className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
                    >
                      <Check size={12} />
                      {t("Save")}
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingMeta(false)}
                      className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                    >
                      {t("Cancel")}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-2.5">
                  <span
                    aria-hidden
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: selected?.color || "#6366F1" }}
                  />
                  <div className="min-w-0 flex-1">
                    <h2 className="truncate text-[14.5px] font-semibold tracking-tight text-[var(--foreground)]">
                      {selected?.name}
                    </h2>
                    {selected?.description && (
                      <p className="truncate text-[11.5px] text-[var(--muted-foreground)]">
                        {selected.description}
                      </p>
                    )}
                  </div>
                  <span className="shrink-0 text-[11px] tabular-nums text-[var(--muted-foreground)]">
                    {selected?.records.length ?? 0} {t("records")}
                  </span>
                  <div className="flex shrink-0 items-center gap-0.5">
                    <HeaderAction
                      label={t("Edit notebook")}
                      icon={Pencil}
                      onClick={beginMetaEdit}
                    />
                    <HeaderAction
                      label={t("Export as Markdown")}
                      icon={Download}
                      onClick={() => void handleExport()}
                    />
                    <HeaderAction
                      label={t("Delete notebook")}
                      icon={Trash2}
                      tone="danger"
                      onClick={() => setConfirmingDelete(true)}
                    />
                  </div>
                </div>
              )}

              {(selected?.records.length ?? 0) > 8 && !editingMeta && (
                <div className="relative">
                  <Search
                    size={12}
                    className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
                  />
                  <input
                    value={recordQuery}
                    onChange={(e) => setRecordQuery(e.target.value)}
                    placeholder={t("Search records in this notebook")}
                    className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] py-1.5 pl-8 pr-2 text-[12px] text-[var(--foreground)] outline-none focus:border-[var(--primary)]/50"
                  />
                </div>
              )}
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto">
              {library.detailLoading ? (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
                </div>
              ) : visibleRecords.length ? (
                <div className="divide-y divide-[var(--border)]/70">
                  {visibleRecords.map((record) => (
                    <NotebookRecordRow
                      key={record.id}
                      record={record}
                      notebooks={notebooks}
                      currentNotebookId={selected!.id}
                      expanded={expandedRecordId === record.id}
                      onToggle={() =>
                        setExpandedRecordId(
                          expandedRecordId === record.id ? null : record.id,
                        )
                      }
                      onEdit={library.editRecord}
                      onDelete={library.removeRecord}
                      onRelocate={library.relocateRecord}
                      onOpenSession={openSession}
                    />
                  ))}
                </div>
              ) : (
                <ConsoleNotice
                  tone="empty"
                  title={
                    recordQuery
                      ? t("No records match your search")
                      : t("This notebook is empty")
                  }
                  detail={
                    recordQuery
                      ? t("Try a different word.")
                      : t(
                          "Save something to it from a chat, research run, or Co-Writer document.",
                        )
                  }
                />
              )}
            </div>
          </>
        )}
      </section>

      <ConfirmDialog
        open={confirmingDelete && Boolean(selected)}
        title={t("Delete this notebook?")}
        confirmLabel={t("Delete")}
        tone="danger"
        busy={deleting}
        onConfirm={() => void handleDeleteNotebook()}
        onCancel={() => setConfirmingDelete(false)}
      >
        <p className="text-[13px] leading-relaxed text-[var(--muted-foreground)]">
          {(selected?.record_count ?? 0) > 0
            ? t(
                '"{{name}}" and its {{count}} records will be deleted. This cannot be undone.',
                {
                  name: selected?.name ?? "",
                  count: selected?.record_count ?? 0,
                },
              )
            : t('"{{name}}" will be deleted.', { name: selected?.name ?? "" })}
        </p>
      </ConfirmDialog>
    </div>
  );
}

function HeaderAction({
  label,
  icon: Icon,
  onClick,
  tone = "default",
}: {
  label: string;
  icon: typeof Pencil;
  onClick: () => void;
  tone?: "default" | "danger";
}) {
  return (
    <Tooltip label={label} side="bottom">
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        className={`inline-flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-[background-color,color,transform] duration-150 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]/40 ${
          tone === "danger"
            ? "hover:bg-[var(--destructive)]/10 hover:text-[var(--destructive)]"
            : "hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        }`}
      >
        <Icon size={13} />
      </button>
    </Tooltip>
  );
}

function ConsoleNotice({
  tone,
  title,
  detail,
  action,
}: {
  tone: "empty" | "error";
  title: string;
  detail: string;
  action?: React.ReactNode;
}) {
  const Icon = tone === "error" ? AlertTriangle : NotebookPen;
  return (
    <div
      role={tone === "error" ? "alert" : undefined}
      className="flex h-full flex-col items-center justify-center gap-2.5 px-6 py-16 text-center"
    >
      <span
        className={`flex h-9 w-9 items-center justify-center rounded-xl ${
          tone === "error"
            ? "bg-[var(--destructive)]/10 text-[var(--destructive)]"
            : "bg-[var(--muted)] text-[var(--muted-foreground)]"
        }`}
      >
        <Icon size={16} />
      </span>
      <p className="text-[13.5px] font-medium text-[var(--foreground)]">
        {title}
      </p>
      <p className="max-w-sm text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
        {detail}
      </p>
      {action}
    </div>
  );
}
