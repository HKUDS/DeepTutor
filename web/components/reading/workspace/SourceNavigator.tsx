"use client";

import {
  BookmarkCheck,
  ChevronDown,
  ChevronRight,
  ListTree,
  PanelLeftClose,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  type OutlineRow,
  type ReadingBookmark,
  type UnitReference,
} from "@/lib/reading-api";
import {
  type OutlineNode,
  type ReaderHeading,
  buildOutlineTree,
  filterOutlineNodes,
  filterReaderHeadings,
} from "@/lib/reading-outline";
import { type ReadingLibraryMaterial } from "@/lib/reading-workspace-api";
import { formatMediaTime, timeFromSourceHref } from "@/lib/reading-media-time";
import { type TranscriptRow } from "./types";

export function SourceNavigator({
  material,
  outline,
  pageHeadings,
  activeHeadingId,
  onNavigateHeading,
  refs,
  transcript,
  transcriptUnavailable,
  chaptersOnly,
  search,
  onSearch,
  activeLocator,
  annotationCount,
  unitCount,
  mobileOpen,
  desktopOpen,
  onMobileClose,
  onCollapse,
  onNavigate,
  bookmarks,
  onRemoveBookmark,
}: {
  material: ReadingLibraryMaterial | null;
  outline: OutlineRow[];
  pageHeadings: ReaderHeading[];
  activeHeadingId: string | null;
  onNavigateHeading: (heading: ReaderHeading) => void;
  refs: UnitReference[];
  transcript: TranscriptRow[];
  transcriptUnavailable: boolean;
  chaptersOnly: boolean;
  search: string;
  onSearch: (value: string) => void;
  activeLocator: number;
  annotationCount: number;
  unitCount: number;
  mobileOpen: boolean;
  desktopOpen: boolean;
  onMobileClose: () => void;
  onCollapse: () => void;
  onNavigate: (locator: number, quote?: string) => void;
  /** Places the reader kept, listed above the outline. */
  bookmarks: ReadingBookmark[];
  onRemoveBookmark: (bookmarkId: string) => void;
}) {
  const { t } = useTranslation();
  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(new Set());
  const mediaSource =
    material?.render_mode === "video" ||
    material?.render_mode === "audio" ||
    material?.source_kind === "youtube" ||
    material?.source_kind === "bilibili";
  const isPdf = material?.render_mode === "pdf";
  const reliableOutline = isPdf
    ? outline.filter((row) => !row.synthesised)
    : outline;
  const pageFallback = isPdf && reliableOutline.length === 0 && unitCount > 0;
  const documentOutline: OutlineRow[] = pageFallback
    ? Array.from({ length: unitCount }, (_, index) => ({
        locator: index + 1,
        title: t("Page {{page}}", { page: index + 1 }),
        level: 1,
        synthesised: false,
      }))
    : reliableOutline;
  const documentTree = useMemo(
    () => filterOutlineNodes(buildOutlineTree(documentOutline), search),
    [documentOutline, search],
  );
  const activeDocumentRow = documentOutline.reduce<OutlineRow | null>(
    (active, row) => (row.locator <= activeLocator ? row : active),
    null,
  );
  const outlineRows = outline.length
    ? outline.map((row) => ({
        locator: row.locator,
        title: chaptersOnly
          ? formatMediaTime(
              timeFromSourceHref(
                refs.find((ref) => ref.locator === row.locator)?.source_href ||
                  "",
              ) || 0,
            )
          : refs.find((ref) => ref.locator === row.locator)?.title ||
            String(row.locator).padStart(2, "0"),
        text: row.title,
        sourceHref:
          refs.find((ref) => ref.locator === row.locator)?.source_href || "",
      }))
    : refs.map((row) => ({
        locator: row.locator,
        title: String(row.locator).padStart(2, "0"),
        text: row.title || "",
        sourceHref: row.source_href,
      }));
  const rows = transcriptUnavailable
    ? chaptersOnly
      ? outlineRows.filter((row) =>
          `${row.title} ${row.text}`
            .toLowerCase()
            .includes(search.toLowerCase()),
        )
      : []
    : transcript.length
      ? transcript.filter((row) =>
          `${row.title} ${row.text}`
            .toLowerCase()
            .includes(search.toLowerCase()),
        )
      : outlineRows;
  // Headings inside the unit the reader is looking at right now. The server
  // outline is document-wide and often coarse (or absent for plain text), so
  // this is the only structure some sources have.
  const visibleHeadings = useMemo(
    () => (mediaSource ? [] : filterReaderHeadings(pageHeadings, search)),
    [mediaSource, pageHeadings, search],
  );
  const rowCount = mediaSource ? rows.length : documentOutline.length;
  const hasAnything = rowCount > 0 || visibleHeadings.length > 0;

  return (
    <aside
      className={`${
        mobileOpen
          ? "absolute inset-y-0 left-0 z-30 flex w-[min(300px,88vw)] shadow-[18px_0_42px_rgba(0,0,0,.12)]"
          : "hidden"
      } min-h-0 min-w-0 flex-col border-r border-[var(--border)] bg-[var(--card)] dark:border-[var(--border)] dark:bg-[var(--card)] ${
        desktopOpen ? "lg:static lg:flex lg:w-auto lg:shadow-none" : "lg:hidden"
      }`}
    >
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-[var(--border)] px-3 dark:border-[var(--border)]">
        <ListTree size={13} className="text-[var(--primary)]" />
        <p className="min-w-0 flex-1 truncate text-[10.5px] font-semibold">
          {material?.render_mode === "video" ||
          material?.render_mode === "audio" ||
          material?.source_kind === "youtube"
            ? chaptersOnly
              ? t("Chapters")
              : t("Transcript")
            : pageFallback
              ? t("Pages")
              : t("Contents")}
        </p>
        {!!annotationCount && (
          <span className="rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-[10px] text-[var(--muted-foreground)]">
            {annotationCount}
          </span>
        )}
        <button
          type="button"
          onClick={onMobileClose}
          className="flex size-6 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--muted)] lg:hidden"
          aria-label={t("Close contents")}
        >
          <X size={11} />
        </button>
        <button
          type="button"
          onClick={onCollapse}
          className="hidden size-6 items-center justify-center rounded-md text-[var(--muted-foreground)] hover:bg-[var(--muted)] lg:flex"
          aria-label={t("Collapse contents")}
        >
          <PanelLeftClose size={12} />
        </button>
      </div>
      <label className="mx-2 mt-2 flex h-8 shrink-0 items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 dark:border-[var(--border)] dark:bg-[var(--card)]">
        <Search size={11} className="text-[var(--muted-foreground)]" />
        <input
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          placeholder={t("Search this material")}
          className="min-w-0 flex-1 bg-transparent text-[10px] outline-none"
        />
      </label>
      <div className="mt-2 min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {bookmarks.length > 0 && (
          /* The reader's own short index, in front of the document's long
             one. Above rather than below because it is the shorter list and
             the one they came here for — scrolling past 74 outline rows to
             reach three saved places would defeat the point. */
          <div className="mb-2 border-b border-[var(--border)] pb-2">
            <p className="flex items-center gap-1.5 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              <BookmarkCheck size={11} className="text-[var(--primary)]" />
              {t("Bookmarks")}
              <span className="tabular-nums opacity-70">
                {bookmarks.length}
              </span>
            </p>
            {bookmarks.map((row) => (
              <div
                key={row.bookmark_id}
                className={`group flex items-center gap-1 rounded-lg transition ${
                  activeLocator === row.locator
                    ? "bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-[var(--primary)]"
                    : "text-[var(--foreground)] hover:bg-[var(--muted)]"
                }`}
              >
                <button
                  type="button"
                  onClick={() => onNavigate(row.locator)}
                  className="flex min-w-0 flex-1 items-baseline gap-2 px-2 py-1.5 text-left"
                >
                  <span className="w-6 shrink-0 text-right text-[10px] tabular-nums text-[var(--muted-foreground)]">
                    {row.locator}
                  </span>
                  {/* A bookmark saved without a label is "this page", so it
                      borrows the outline's own heading for that locator
                      rather than making the reader name a place before they
                      are allowed to keep it. */}
                  <span className="line-clamp-2 min-w-0 text-[10.5px] leading-[1.5]">
                    {row.label ||
                      outline.find((entry) => entry.locator === row.locator)
                        ?.title ||
                      t("p. {{page}}", { page: row.locator })}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => onRemoveBookmark(row.bookmark_id)}
                  aria-label={t("Remove this bookmark")}
                  className="mr-1 shrink-0 rounded-md p-1 text-[var(--muted-foreground)] opacity-0 transition hover:bg-[var(--accent)] hover:text-[var(--foreground)] focus-visible:opacity-100 group-hover:opacity-100"
                >
                  <Trash2 size={11} />
                </button>
              </div>
            ))}
          </div>
        )}
        {!hasAnything ? (
          <div className="px-2 py-4 text-[10px] leading-relaxed text-[var(--muted-foreground)]">
            {mediaSource && transcriptUnavailable ? (
              <>
                <p className="font-medium text-[var(--muted-foreground)]">
                  {t("No transcript available")}
                </p>
                <p className="mt-1">
                  {t(
                    "Playback still works. Transcript-grounded explanation and timestamp search are unavailable for this video.",
                  )}
                </p>
              </>
            ) : (
              <p>
                {material?.status === "ready"
                  ? t("This material has no outline to navigate yet.")
                  : t("The outline appears once processing finishes.")}
              </p>
            )}
          </div>
        ) : mediaSource ? (
          rows.map((row) => (
            <button
              key={row.locator}
              type="button"
              onClick={() =>
                onNavigate(
                  row.locator,
                  !chaptersOnly && transcript.length ? row.text : undefined,
                )
              }
              className={`group mb-0.5 flex w-full items-baseline gap-2 rounded-lg px-2 py-1.5 text-left transition ${
                activeLocator === row.locator
                  ? "bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-[var(--primary)]"
                  : "text-[var(--foreground)] hover:bg-[var(--muted)]"
              }`}
            >
              {/* Same weighting as the document outline: the line of speech is
                  what is read, the timestamp is how you get back to it. */}
              <span className="w-9 shrink-0 text-right text-[10px] tabular-nums text-[var(--muted-foreground)]">
                {row.title || row.locator}
              </span>
              <span className="line-clamp-3 min-w-0 text-[10.5px] leading-[1.5]">
                {row.text}
              </span>
            </button>
          ))
        ) : (
          <>
            <WorkspaceOutlineBranch
              nodes={documentTree}
              activeRow={activeDocumentRow}
              pageFallback={pageFallback}
              collapsedNodes={search ? new Set() : collapsedNodes}
              onToggle={(key) =>
                setCollapsedNodes((current) => {
                  const next = new Set(current);
                  if (next.has(key)) next.delete(key);
                  else next.add(key);
                  return next;
                })
              }
              onNavigate={onNavigate}
            />
            {visibleHeadings.length > 0 && (
              <section
                aria-label={t("On this page")}
                className={
                  rowCount ? "mt-3 border-t border-[var(--border)] pt-2" : ""
                }
              >
                <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.07em] text-[var(--muted-foreground)]">
                  {t("On this page")}
                </p>
                {visibleHeadings.map((heading) => (
                  <button
                    key={heading.id}
                    type="button"
                    onClick={() => onNavigateHeading(heading)}
                    style={{
                      paddingLeft: `${8 + (Math.min(heading.level, 4) - 1) * 10}px`,
                    }}
                    className={`mb-0.5 block w-full truncate rounded-lg py-1.5 pr-2 text-left text-[10px] leading-[1.4] transition ${
                      activeHeadingId === heading.id
                        ? "bg-[var(--muted)] font-medium text-[var(--primary)]"
                        : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                    }`}
                    title={heading.title}
                  >
                    {heading.title}
                  </button>
                ))}
              </section>
            )}
          </>
        )}
      </div>
      <div className="shrink-0 border-t border-[var(--border)] px-3 py-2 text-[10px] text-[var(--muted-foreground)] dark:border-[var(--border)]">
        {material?.status === "ready"
          ? mediaSource
            ? t("{{count}} passages available to the companion", {
                count: rowCount,
              })
            : pageFallback
              ? t("{{count}} pages", { count: rowCount })
              : t("{{count}} outline entries", { count: rowCount })
          : t(material?.status || "queued")}
      </div>
    </aside>
  );
}

export function WorkspaceOutlineBranch({
  nodes,
  activeRow,
  pageFallback,
  collapsedNodes,
  onToggle,
  onNavigate,
  depth = 0,
}: {
  nodes: OutlineNode[];
  activeRow: OutlineRow | null;
  pageFallback: boolean;
  collapsedNodes: Set<string>;
  onToggle: (key: string) => void;
  onNavigate: (locator: number) => void;
  depth?: number;
}) {
  const { t } = useTranslation();
  return (
    <ul className={depth ? "ml-2 border-l border-[var(--border)] pl-1" : ""}>
      {nodes.map((node) => {
        const key = `${node.row.locator}-${node.row.title}`;
        const active = node.row === activeRow;
        const collapsed = collapsedNodes.has(key);
        return (
          <li key={key} className="mb-0.5 min-w-0">
            <div
              className={`group flex items-center gap-1 rounded-lg transition ${
                active
                  ? "bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-[var(--primary)]"
                  : "text-[var(--foreground)] hover:bg-[var(--muted)]"
              }`}
            >
              <button
                type="button"
                onClick={() => onNavigate(node.row.locator)}
                // The spelled-out locator is the tooltip rather than the label:
                // see the number column below.
                title={t("p. {{page}}", { page: node.row.locator })}
                className="flex min-w-0 flex-1 items-baseline gap-2 px-2 py-1.5 text-left"
              >
                {/* A table of contents is read by its titles, so the title
                    carries the weight and the locator is the quiet column
                    beside it — the other way round, 74 blue page numbers
                    out-shouted the headings they were pointing at.

                    It is also just the number. "p. 12" fits the 32px this
                    column had, but every translation of it does not: in
                    Chinese ("第 12 页") 65 of this document's 74 rows wrapped
                    onto a second line, so the list had two different row
                    heights and a ragged left edge for the titles. Right-
                    aligned tabular digits are what a printed contents page
                    does anyway, and no translation can outgrow them. */}
                <span className="w-6 shrink-0 text-right text-[10px] tabular-nums text-[var(--muted-foreground)]">
                  {node.row.locator}
                </span>
                <span className="line-clamp-3 min-w-0 text-[10.5px] leading-[1.5]">
                  {node.row.title}
                </span>
              </button>
              {node.children.length > 0 && (
                <button
                  type="button"
                  onClick={() => onToggle(key)}
                  aria-expanded={!collapsed}
                  aria-label={
                    collapsed ? t("Expand section") : t("Collapse section")
                  }
                  className="mr-1 shrink-0 rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
                >
                  {collapsed ? (
                    <ChevronRight size={11} />
                  ) : (
                    <ChevronDown size={11} />
                  )}
                </button>
              )}
            </div>
            {node.children.length > 0 && !collapsed && (
              <WorkspaceOutlineBranch
                nodes={node.children}
                activeRow={activeRow}
                pageFallback={pageFallback}
                collapsedNodes={collapsedNodes}
                onToggle={onToggle}
                onNavigate={onNavigate}
                depth={depth + 1}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}
