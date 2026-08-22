"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  Folder,
  Globe,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
} from "lucide-react";
import type {
  WebNavNode,
  WebNavigationSource,
} from "@/lib/knowledge-api";
import { docIconFor } from "@/lib/doc-attachments";

interface WebNavigationTreeProps {
  sources: WebNavigationSource[];
  loading: boolean;
  selectedFile: string | null;
  onSelect: (filePath: string) => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onRefresh: () => void;
}

/**
 * Pure-presentational sidebar navigation for web-source KBs.  Data is
 * fetched by the parent (KbFilesTab) and passed in as props.
 */
export default function WebNavigationTree({
  sources,
  loading,
  selectedFile,
  onSelect,
  collapsed,
  onToggleCollapsed,
  onRefresh,
}: WebNavigationTreeProps) {
  const { t } = useTranslation();
  const [expandedOverrides, setExpandedOverrides] = useState<
    Record<string, boolean>
  >({});

  const defaultExpanded = useMemo(() => {
    const top = new Set<string>();
    for (const src of sources) {
      for (const node of src.nodes) {
        if (node.children.length > 0) top.add(node.id);
      }
    }

    if (selectedFile) {
      for (const src of sources) {
        const found = findPathToFile(src.nodes, selectedFile);
        if (found) {
          for (const node of found) top.add(node.id);
          break;
        }
      }
    }

    return top;
  }, [selectedFile, sources]);

  const expanded = useMemo(() => {
    const effective = new Set(defaultExpanded);
    for (const [id, isExpanded] of Object.entries(expandedOverrides)) {
      if (isExpanded) effective.add(id);
      else effective.delete(id);
    }
    return effective;
  }, [defaultExpanded, expandedOverrides]);

  const toggleNode = useCallback(
    (id: string) => {
      setExpandedOverrides((prev) => ({
        ...prev,
        [id]: !expanded.has(id),
      }));
    },
    [expanded],
  );

  if (collapsed) {
    // Collapsed: show icon-only strip with expand button and quick file access.
    const allLeaves = sources.flatMap((s) => s.nodes).filter((n) => n.file_path);
    return (
      <aside className="flex h-full w-[44px] shrink-0 flex-col items-center gap-1 border-r border-[var(--border)] bg-[var(--card)]/40 py-2">
        <button
          type="button"
          onClick={onToggleCollapsed}
          title={t("Expand")}
          aria-label={t("Expand")}
          className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <PanelLeftOpen size={13} strokeWidth={1.7} />
        </button>
        <div className="my-1 h-px w-6 bg-[var(--border)]/60" />
        <div className="flex w-full flex-1 flex-col items-center gap-0.5 overflow-y-auto pb-2">
          {allLeaves.map((node) => {
            const spec = docIconFor(node.file_path);
            const Icon = spec.Icon;
            const active = selectedFile === node.file_path;
            return (
              <button
                key={node.id}
                type="button"
                onClick={() => onSelect(node.file_path)}
                title={node.title}
                aria-label={node.title}
                className={`relative flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition-colors ${
                  active
                    ? "bg-[var(--primary)]/12 ring-1 ring-[var(--primary)]/40"
                    : "hover:bg-[var(--muted)]/60"
                }`}
              >
                {active && (
                  <span className="absolute -left-1 top-1/2 h-4 w-[2.5px] -translate-y-1/2 rounded-full bg-[var(--primary)]" />
                )}
                <Icon size={13} strokeWidth={1.6} className={spec.tint} />
              </button>
            );
          })}
        </div>
      </aside>
    );
  }

  if (loading) {
    return (
      <aside className="flex h-full w-[240px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--card)]/40">
        <div className="flex items-center justify-between px-2.5 py-2.5">
          <span className="text-[12px] font-medium text-[var(--foreground)]">
            {t("Contents")}
          </span>
          <Loader2 className="h-3 w-3 animate-spin text-[var(--muted-foreground)]" />
        </div>
      </aside>
    );
  }

  const renderNode = (node: WebNavNode, depth: number): React.ReactNode => {
    const hasChildren = node.children.length > 0;
    const isOpen = expanded.has(node.id);
    const isActive = node.file_path === selectedFile;
    const indent = { paddingLeft: `${depth * 12 + 8}px` };

    if (hasChildren) {
      return (
        <li key={node.id}>
          <div
            style={indent}
            className="flex cursor-pointer items-center gap-1 rounded-md py-1.5 pr-2 transition-colors hover:bg-[var(--muted)]/50"
          >
            <button
              type="button"
              onClick={() => toggleNode(node.id)}
              className="flex min-w-0 flex-1 items-center gap-1 text-left"
            >
              {isOpen ? (
                <ChevronDown className="h-3 w-3 shrink-0 text-[var(--muted-foreground)]" />
              ) : (
                <ChevronRight className="h-3 w-3 shrink-0 text-[var(--muted-foreground)]" />
              )}
              <Folder className="h-3.5 w-3.5 shrink-0 text-[var(--muted-foreground)]" />
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-[12px] font-medium text-[var(--foreground)]">
                  {node.title}
                </span>
                {node.title_zh && node.title_zh !== node.title && (
                  <span className="truncate text-[10px] text-[var(--muted-foreground)]/60">
                    {node.title_zh}
                  </span>
                )}
              </span>
            </button>
            {node.file_path && (
              <button
                type="button"
                onClick={() => onSelect(node.file_path)}
                className="shrink-0 rounded p-0.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                title={t("Open page")}
              >
                <FileText size={11} strokeWidth={1.5} />
              </button>
            )}
          </div>
          {isOpen && (
            <ul className="space-y-px">
              {node.children.map((child) => renderNode(child, depth + 1))}
            </ul>
          )}
        </li>
      );
    }

    return (
      <li key={node.id}>
        <div
          style={indent}
          className={`relative flex items-center gap-2 rounded-md py-1.5 pr-2 transition-colors ${
            isActive
              ? "bg-[var(--primary)]/10"
              : "hover:bg-[var(--muted)]/50"
          }`}
        >
          {isActive && (
            <span
              className="absolute left-0 top-1/2 h-3.5 w-[2.5px] -translate-y-1/2 rounded-full bg-[var(--primary)]"
              style={{ marginLeft: `${depth * 12 + 2}px` }}
            />
          )}
          {node.file_path ? (
            <button
              type="button"
              onClick={() => onSelect(node.file_path)}
              className="flex min-w-0 flex-1 items-center gap-2 text-left"
            >
              <FileText
                size={13}
                strokeWidth={1.6}
                className={`shrink-0 ${isActive ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"}`}
              />
              <span className="flex min-w-0 flex-col">
                <span
                  className={`truncate text-[12px] ${isActive ? "font-medium text-[var(--foreground)]" : "text-[var(--foreground)]"}`}
                >
                  {node.title}
                </span>
                {node.title_zh && node.title_zh !== node.title && (
                  <span className="truncate text-[10px] text-[var(--muted-foreground)]/70">
                    {node.title_zh}
                  </span>
                )}
              </span>
            </button>
          ) : (
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <FileText
                size={13}
                strokeWidth={1.6}
                className="shrink-0 text-[var(--muted-foreground)]"
              />
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-[12px] text-[var(--muted-foreground)]">
                  {node.title}
                </span>
                {node.title_zh && node.title_zh !== node.title && (
                  <span className="truncate text-[10px] text-[var(--muted-foreground)]/60">
                    {node.title_zh}
                  </span>
                )}
              </span>
            </div>
          )}
          <a
            href={node.url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 rounded p-0.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            title={t("Open original")}
          >
            <ExternalLink size={10} strokeWidth={1.5} />
          </a>
        </div>
      </li>
    );
  };

  return (
    <aside className="flex h-full w-[240px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--card)]/40">
      <div className="flex items-center justify-between gap-1 px-2.5 pb-1.5 pt-2.5">
        <span className="text-[12px] font-medium text-[var(--foreground)]">
          {t("Contents")}
        </span>
        <div className="flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            onClick={onRefresh}
            title={t("Refresh")}
            aria-label={t("Refresh")}
            className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <RefreshCw size={12} strokeWidth={1.7} />
          </button>
          <button
            type="button"
            onClick={onToggleCollapsed}
            title={t("Collapse")}
            aria-label={t("Collapse")}
            className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
          >
            <PanelLeftClose size={12} strokeWidth={1.7} />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-1.5 pb-2.5">
        {sources.map((src) => (
          <div key={src.source_id} className="mb-3">
            <div className="flex items-center gap-1.5 px-1 py-1">
              <Globe className="h-3 w-3 shrink-0 text-[var(--muted-foreground)]" />
              <span className="truncate text-[10.5px] uppercase tracking-wide text-[var(--muted-foreground)]">
                {src.source_url.replace(/^https?:\/\//, "").split("/")[0]}
              </span>
            </div>
            {src.kind === "inferred" && (
              <div className="px-1 pb-1 text-[10px] text-[var(--muted-foreground)]/70">
                {t("Auto-generated structure")}
              </div>
            )}
            <ul className="space-y-px">
              {src.nodes.map((node) => renderNode(node, 0))}
            </ul>
          </div>
        ))}
      </div>
    </aside>
  );
}

/** Find the chain of ancestor nodes leading to a file_path. */
function findPathToFile(
  nodes: WebNavNode[],
  filePath: string,
): WebNavNode[] | null {
  for (const node of nodes) {
    if (node.file_path === filePath) return [node];
    if (node.children.length > 0) {
      const found = findPathToFile(node.children, filePath);
      if (found) return [node, ...found];
    }
  }
  return null;
}
