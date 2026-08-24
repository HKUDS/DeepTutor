"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { RefObject } from "react";
import type { OutlineRow } from "@/lib/reading-api";
import {
  buildOutlineTree,
  filterOutlineNodes,
  filterReaderHeadings,
  type OutlineNode,
  type ReaderHeading,
} from "@/lib/reading-outline";

interface ReaderOutlineProps {
  rows: OutlineRow[];
  sourcePaths?: string[];
  sourceType?: string;
  pageHeadings: ReaderHeading[];
  activeHeadingId?: string | null;
  currentLocator: number;
  onNavigate: (locator: number) => void;
  onNavigateHeading: (heading: ReaderHeading) => void;
  onClose: () => void;
}

export function ReaderOutline({
  rows,
  sourcePaths,
  sourceType,
  pageHeadings,
  activeHeadingId,
  currentLocator,
  onNavigate,
  onNavigateHeading,
  onClose,
}: ReaderOutlineProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"document" | "page">("document");
  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(new Set());
  const activeOutlineRef = useRef<HTMLButtonElement | null>(null);
  const activeHeadingRef = useRef<HTMLButtonElement | null>(null);

  const tree = useMemo(() => buildOutlineTree(rows, sourcePaths), [rows, sourcePaths]);
  const visibleTree = useMemo(
    () => filterOutlineTree(tree, query),
    [query, tree],
  );
  const visiblePageHeadings = useMemo(
    () => filterReaderHeadings(pageHeadings, query),
    [pageHeadings, query],
  );
  const activeIndex = useMemo(() => {
    let active = -1;
    rows.forEach((row, index) => {
      if (row.locator <= currentLocator) active = index;
    });
    return active;
  }, [rows, currentLocator]);
  const hasCollapsibleNodes = tree.some((node) => node.children.length > 0);
  const hasBothViews = tree.length > 0 && pageHeadings.length > 0;
  const showDocumentView = activeTab === "document" && tree.length > 0;
  const showPageView =
    (activeTab === "page" || tree.length === 0) && pageHeadings.length > 0;
  const documentTabLabel =
    sourceType === "kb_web_tutorial"
      ? t("Website contents")
      : t("Document contents");

  useEffect(() => {
    if (showDocumentView) activeOutlineRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, showDocumentView]);
  useEffect(() => {
    if (showPageView) activeHeadingRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeHeadingId, showPageView]);

  const setAllCollapsed = (collapsed: boolean) => {
    setCollapsedNodes(
      collapsed
        ? new Set(collectCollapsibleKeys(tree))
        : new Set(),
    );
  };

  const switchTab = (tab: "document" | "page") => {
    setActiveTab(tab);
    setQuery("");
  };

  return (
    <aside
      aria-label={t("Contents")}
      className="dt-reader-scroll absolute inset-y-0 left-0 z-20 flex w-72 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--card)]/95 backdrop-blur sm:w-72 md:relative md:z-auto md:w-64 md:bg-[var(--card)]/45 md:backdrop-blur-none lg:w-[17rem]"
    >
      <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-[var(--border)] px-2">
        <span className="min-w-0 truncate text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
          {hasBothViews
            ? activeTab === "document"
              ? documentTabLabel
              : t("On this page")
            : tree.length > 0
              ? t("Contents")
              : t("On this page")}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          {showDocumentView && hasCollapsibleNodes && (
            <>
              <button
                type="button"
                onClick={() => setAllCollapsed(false)}
                className="rounded px-1 py-0.5 text-[10px] text-[var(--muted-foreground)] transition hover:text-[var(--foreground)]"
              >
                {t("Expand all")}
              </button>
              <button
                type="button"
                onClick={() => setAllCollapsed(true)}
                className="rounded px-1 py-0.5 text-[10px] text-[var(--muted-foreground)] transition hover:text-[var(--foreground)]"
              >
                {t("Collapse all")}
              </button>
            </>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label={t("Close outline")}
            className="rounded p-1 text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <X size={12} />
          </button>
        </div>
      </div>
      {hasBothViews && (
        <div
          role="tablist"
          aria-label={t("Contents")}
          className="grid shrink-0 grid-cols-2 gap-1 border-b border-[var(--border)] p-1.5"
        >
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "document"}
            onClick={() => switchTab("document")}
            className={`h-7 rounded-md px-2 text-[11.5px] font-medium transition ${
              activeTab === "document"
                ? "bg-[var(--primary)]/12 text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {documentTabLabel}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "page"}
            onClick={() => switchTab("page")}
            className={`h-7 rounded-md px-2 text-[11.5px] font-medium transition ${
              activeTab === "page"
                ? "bg-[var(--primary)]/12 text-[var(--primary)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {t("On this page")}
          </button>
        </div>
      )}
      <label className="flex h-9 shrink-0 items-center gap-1.5 border-b border-[var(--border)] px-2 text-[var(--muted-foreground)]">
        <Search size={12} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("Filter contents")}
          className="min-w-0 flex-1 bg-transparent text-[11.5px] text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)]"
        />
      </label>
      <nav className="min-h-0 flex-1 overflow-y-auto px-1.5 py-2">
        {showDocumentView && (
          <OutlineBranch
            nodes={visibleTree}
            rows={rows}
            activeIndex={activeIndex}
            collapsedNodes={query ? new Set() : collapsedNodes}
            onToggle={(key) =>
              setCollapsedNodes((current) => {
                const next = new Set(current);
                if (next.has(key)) next.delete(key);
                else next.add(key);
                return next;
              })
            }
            onNavigate={onNavigate}
            activeOutlineRef={activeOutlineRef}
          />
        )}
        {showPageView && (
          <PageHeadingList
            headings={visiblePageHeadings}
            activeHeadingId={activeHeadingId}
            onNavigate={onNavigateHeading}
            activeHeadingRef={activeHeadingRef}
          />
        )}
      </nav>
    </aside>
  );
}

function PageHeadingList({
  headings,
  activeHeadingId,
  onNavigate,
  activeHeadingRef,
}: {
  headings: ReaderHeading[];
  activeHeadingId?: string | null;
  onNavigate: (heading: ReaderHeading) => void;
  activeHeadingRef: RefObject<HTMLButtonElement | null>;
}) {
  return (
    <ul className="space-y-0.5">
      {headings.map((heading) => (
        <li key={heading.id} className="min-w-0">
          <button
            type="button"
            ref={activeHeadingId === heading.id ? activeHeadingRef : undefined}
            onClick={() => onNavigate(heading)}
            style={{ marginLeft: (heading.level - 1) * 9 }}
            className={`flex w-full items-center gap-1.5 rounded-md py-[6px] pl-1.5 pr-1 text-left transition hover:bg-[var(--muted)] ${
              activeHeadingId === heading.id
                ? "bg-[var(--primary)]/12 text-[var(--primary)]"
                : "text-[var(--foreground)]/85"
            }`}
          >
            <span className="min-w-0 flex-1 truncate text-[12px] leading-5">
              {heading.title}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function OutlineBranch({
  nodes,
  rows,
  activeIndex,
  collapsedNodes,
  onToggle,
  onNavigate,
  activeOutlineRef,
  depth = 0,
}: {
  nodes: OutlineNode[];
  rows: OutlineRow[];
  activeIndex: number;
  collapsedNodes: Set<string>;
  onToggle: (key: string) => void;
  onNavigate: (locator: number) => void;
  activeOutlineRef: RefObject<HTMLButtonElement | null>;
  depth?: number;
}) {
  const { t } = useTranslation();
  return (
    <ul className={`space-y-0.5 ${depth === 0 ? "" : "mt-0.5 pl-1.5"}`}>
      {nodes.map((node) => {
        const key = `${node.row.locator}-${node.row.title}`;
        const isActive = rows[activeIndex] === node.row;
        const collapsed = collapsedNodes.has(key);
        return (
          <li key={key} className="min-w-0">
            <div
              className={`group/nav flex items-center gap-1 rounded-md pr-1 transition hover:bg-[var(--muted)] ${
                isActive ? "bg-[var(--primary)]/10" : ""
              }`}
              style={{ marginLeft: depth === 0 ? 0 : 10 }}
            >
              <button
                type="button"
                onClick={() => onNavigate(node.row.locator)}
                ref={isActive ? activeOutlineRef : undefined}
                className={`flex min-w-0 flex-1 items-center gap-1.5 py-[6px] pl-1.5 text-left ${
                  depth === 0
                    ? "font-medium text-[var(--foreground)]"
                    : "text-[var(--foreground)]/85"
                }`}
              >
                {depth > 0 && (
                  <span aria-hidden="true" className="h-4 w-px shrink-0 bg-[var(--border)]" />
                )}
                <span className="min-w-0 flex-1 truncate text-[12px] leading-5">
                  {node.row.title}
                </span>
              </button>
              {node.row.source_url && (
                <a
                  href={node.row.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={t("Open original page")}
                  aria-label={`${node.row.title} — ${t("Open original page")}`}
                  className="shrink-0 rounded p-1 text-[var(--muted-foreground)] opacity-70 transition hover:text-[var(--foreground)] hover:opacity-100 focus-visible:opacity-100"
                >
                  <ExternalLink size={10.5} />
                </a>
              )}
              {node.children.length > 0 && (
                <button
                  type="button"
                  onClick={() => onToggle(key)}
                  aria-expanded={!collapsed}
                  aria-label={collapsed ? t("Expand section") : t("Collapse section")}
                  className="shrink-0 rounded p-1 text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                >
                  {collapsed ? <ChevronRight size={11} /> : <ChevronDown size={11} />}
                </button>
              )}
            </div>
            {node.children.length > 0 && !collapsed && (
              <OutlineBranch
                nodes={node.children}
                rows={rows}
                activeIndex={activeIndex}
                collapsedNodes={collapsedNodes}
                onToggle={onToggle}
                onNavigate={onNavigate}
                activeOutlineRef={activeOutlineRef}
                depth={depth + 1}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}

function filterOutlineTree(nodes: OutlineNode[], query: string): OutlineNode[] {
  return filterOutlineNodes(nodes, query);
}

function collectCollapsibleKeys(nodes: OutlineNode[]): string[] {
  return nodes.flatMap((node) => [
    `${node.row.locator}-${node.row.title}`,
    ...collectCollapsibleKeys(node.children),
  ]);
}
