"use client";
import { ChevronLeft, ChevronRight } from "lucide-react";


import { useCallback, useEffect, useMemo, useState } from "react";
import {
  knowledgeBaseFilePath,
  knowledgeBaseFilePreviewTextPath,
  getWebNavigation,
  type KnowledgeBaseFile,
  type WebNavigationSource,
} from "@/lib/knowledge-api";
import type { KnowledgeBase } from "@/lib/knowledge-helpers";
import type { TaskState } from "@/hooks/useKnowledgeProgress";
import type { FilePreviewSource } from "@/components/chat/preview/previewerFor";
import { useCollapsiblePanel } from "@/hooks/useCollapsiblePanel";
import KbDocumentList from "./KbDocumentList";
import KbFilePreview from "./KbFilePreview";
import WebNavigationTree from "./WebNavigationTree";

interface KbFilesTabProps {
  kb: KnowledgeBase;
  task?: TaskState;
}

/**
 * Master-detail view for the "Files" tab: list of raw documents on the
 * left, inline preview pane on the right. When the KB has web sources
 * with navigation data, the sidebar switches from a flat file list to
 * the site's original page hierarchy.
 */
export default function KbFilesTab({ kb, task }: KbFilesTabProps) {
  const [selectedFile, setSelectedFile] = useState<KnowledgeBaseFile | null>(
    null,
  );
  const [navSources, setNavSources] = useState<WebNavigationSource[]>([]);
  const [navLoading, setNavLoading] = useState(true);
  const [navRefreshKey, setNavRefreshKey] = useState(0);
  const fileListPanel = useCollapsiblePanel("knowledge-file-list");

  // Fetch navigation data once for this KB.  WebNavigationTree receives
  // the data as props instead of making its own API call.
  const loadNav = useCallback(async () => {
    try {
      setNavSources(await getWebNavigation(kb.name));
    } catch {
      setNavSources([]);
    } finally {
      setNavLoading(false);
    }
  }, [kb.name]);

  useEffect(() => {
    void loadNav();
  }, [loadNav, navRefreshKey]);

  const hasWebNav = navSources.some((s) => s.nodes.length > 0);

  // Bump refreshKey when the active create/upload task settles so newly
  // indexed files appear automatically.
  const taskExecuting = task?.executing === true;
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => {
    if (!taskExecuting) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRefreshKey((n) => n + 1);
    }
  }, [taskExecuting]);

  const previewSource = useMemo<FilePreviewSource | null>(() => {
    if (!selectedFile) return null;
    return {
      filename: selectedFile.name,
      mimeType: selectedFile.mime_type ?? undefined,
      url: knowledgeBaseFilePath(kb.name, selectedFile.name),
      extractedTextUrl: knowledgeBaseFilePreviewTextPath(
        kb.name,
        selectedFile.name,
      ),
      size: selectedFile.size,
      id: `${kb.name}/${selectedFile.name}`,
    };
  }, [kb.name, selectedFile]);

  // Flatten navigation leaves for prev/next navigation.
  const navLeaves = useMemo(() => {
    if (!hasWebNav) return [] as { path: string; title: string }[];
    const leaves: { path: string; title: string }[] = [];
    const walk = (nodes: typeof navSources[number]["nodes"]) => {
      for (const node of nodes) {
        if (node.file_path) {
          leaves.push({ path: node.file_path, title: node.title });
        }
        if (node.children.length) walk(node.children);
      }
    };
    for (const src of navSources) walk(src.nodes);
    return leaves;
  }, [navSources, hasWebNav]);

  const currentIndex = selectedFile
    ? navLeaves.findIndex((l) => l.path === selectedFile.name)
    : -1;
  const prevPage = currentIndex > 0 ? navLeaves[currentIndex - 1] : null;
  const nextPage =
    currentIndex >= 0 && currentIndex < navLeaves.length - 1
      ? navLeaves[currentIndex + 1]
      : null;

  return (
    <div className="flex h-full min-h-0">
      {hasWebNav ? (
        <WebNavigationTree
          sources={navSources}
          loading={navLoading}
          selectedFile={selectedFile?.name ?? null}
          onSelect={(filePath) => setSelectedFile({ name: filePath })}
          collapsed={fileListPanel.collapsed}
          onToggleCollapsed={fileListPanel.toggle}
          onRefresh={() => setNavRefreshKey((n) => n + 1)}
        />
      ) : (
        <KbDocumentList
          kbName={kb.name}
          refreshKey={refreshKey}
          selectedFile={selectedFile?.name ?? null}
          onSelect={setSelectedFile}
          collapsed={fileListPanel.collapsed}
          onToggleCollapsed={fileListPanel.toggle}
        />
      )}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <KbFilePreview
          source={previewSource}
          fileListCollapsed={fileListPanel.collapsed}
          onToggleFileList={fileListPanel.toggle}
          kbName={kb.name}
          filePath={selectedFile?.name}
          onNavigate={(path) => setSelectedFile({ name: path })}
        />
        {hasWebNav && (prevPage || nextPage) && (
          <div className="flex shrink-0 items-center justify-between gap-3 border-t border-[var(--border)] bg-[var(--card)]/60 px-6 py-2">
            {prevPage ? (
              <button
                type="button"
                onClick={() => setSelectedFile({ name: prevPage.path })}
                className="flex min-w-0 items-center gap-1.5 rounded-md px-2 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <ChevronLeft size={14} strokeWidth={1.7} className="shrink-0" />
                <span className="truncate">{prevPage.title}</span>
              </button>
            ) : (
              <span />
            )}
            {nextPage ? (
              <button
                type="button"
                onClick={() => setSelectedFile({ name: nextPage.path })}
                className="flex min-w-0 items-center justify-end gap-1.5 rounded-md px-2 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
              >
                <span className="truncate">{nextPage.title}</span>
                <ChevronRight size={14} strokeWidth={1.7} className="shrink-0" />
              </button>
            ) : (
              <span />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
