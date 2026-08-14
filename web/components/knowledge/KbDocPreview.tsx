"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import DictionaryPanel from "@/components/common/DictionaryPanel";
import { useTextSource } from "@/components/chat/preview/previewers/useTextSource";
import { useWordLookup } from "@/hooks/useWordLookup";
import {
  getBilingualPage,
  listKnowledgeBaseFiles,
  type BilingualAlignGroup,
  type BilingualPage,
  type KnowledgeBaseFile,
} from "@/lib/knowledge-api";
import { resolveKbLink } from "@/lib/kb-links";

/**
 * Documentation-oriented markdown preview for KB files.
 *
 * When a bilingual alignment sidecar exists, renders a structured bilingual
 * view: English content is shown natively, with collapsible Chinese panels
 * rendered as native <details> elements below each aligned group.
 *
 * Falls back to the legacy markdown-only renderer when no alignment exists
 * (non-web-source KBs, unpaired pages, or old inline <details> files).
 */
interface KbDocPreviewProps {
  url: string;
  /** KB name — enables internal link resolution + dictionary context. */
  kbName?: string;
  /** Path of the file being previewed (POSIX, relative to raw/). */
  filePath?: string;
  /** Called with a resolved local file path when an internal link is clicked. */
  onNavigate?: (path: string) => void;
}


/** One bilingual content group: EN rendered natively + collapsible ZH panel.
 *  Memoized so toggling "expand all" doesn't re-render every group's markdown. */
const BilingualGroupItem = memo(function BilingualGroupItem({
  group,
}: {
  group: BilingualAlignGroup;
}) {
  const hasZh =
    group.zh_content &&
    group.zh_content.trim() &&
    !group.show_once.includes("code") &&
    !group.show_once.includes("image") &&
    !group.show_once.includes("hr");

  return (
    <div>
      {group.en_content && group.en_content.trim() && (
        <MarkdownRenderer content={group.en_content} variant="prose" allowHtml />
      )}
      {hasZh && (
        <details data-zh-translation="true" className="mt-1 mb-3">
          <summary className="cursor-pointer text-[12px] font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
            📖 中文翻译
          </summary>
          <div className="mt-2 border-l-2 border-[var(--primary)]/20 pl-4 text-[var(--foreground)]">
            <MarkdownRenderer content={group.zh_content!} variant="prose" allowHtml />
          </div>
        </details>
      )}
    </div>
  );
});

export default function KbDocPreview({
  url,
  kbName,
  filePath,
  onNavigate,
}: KbDocPreviewProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const [allExpanded, setAllExpanded] = useState(false);
  const [zhCount, setZhCount] = useState(0);
  const [files, setFiles] = useState<KnowledgeBaseFile[]>([]);
  const state = useTextSource(url);
  const dict = useWordLookup(containerRef, {
    enabled: state.kind === "ready",
    resetKey: url,
  });

  // Bilingual alignment data for this file.
  const [bilingual, setBilingual] = useState<BilingualPage | null>(null);
  const [bilingualLoading, setBilingualLoading] = useState(false);

  useEffect(() => {
    if (!kbName || !filePath) {
      setBilingual(null);
      return;
    }
    let cancelled = false;
    setBilingualLoading(true);
    setBilingual(null);
    getBilingualPage(kbName, filePath)
      .then((data) => {
        if (!cancelled) setBilingual(data);
      })
      .catch(() => {
        // non-critical: falls back to monolingual rendering
      })
      .finally(() => {
        if (!cancelled) setBilingualLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [kbName, filePath]);

  // Determine if we have structured bilingual groups to render.
  const hasStructuredBilingual =
    bilingual?.page_class === "bilingual" &&
    Array.isArray(bilingual.groups) &&
    bilingual.groups.length > 0;

  // After content renders, tag Chinese-translation details blocks so CSS
  // can give them a distinct visual treatment.
  useEffect(() => {
    if (state.kind !== "ready" || !containerRef.current) return;
    let attempts = 0;
    const maxAttempts = 10;
    const timer = setInterval(() => {
      if (!containerRef.current) {
        clearInterval(timer);
        return;
      }
      const details = containerRef.current.querySelectorAll("details");
      if (details.length === 0 && attempts < maxAttempts) {
        attempts++;
        return;
      }
      clearInterval(timer);
      let count = 0;
      details.forEach((d) => {
        const summary = d.querySelector("summary");
        const isZh = summary?.textContent?.includes("中文翻译");
        if (isZh) {
          d.setAttribute("data-zh-translation", "true");
          count++;
        }
      });
      setZhCount(count);
      setAllExpanded(false);
    }, 100);
    return () => clearInterval(timer);
  }, [state, bilingual]);

  // Load the KB file list for internal link resolution.
  useEffect(() => {
    if (!kbName) return;
    let cancelled = false;
    listKnowledgeBaseFiles(kbName)
      .then((next) => {
        if (!cancelled) setFiles(next);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [kbName]);

  // Intercept internal doc links.
  useEffect(() => {
    const ref = containerRef.current;
    if (!ref || !onNavigate) return;
    const onClick = (event: MouseEvent) => {
      if (
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }
      const anchor = (event.target as HTMLElement | null)?.closest?.("a");
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (!href) return;
      const localPath = resolveKbLink(href, filePath ?? "", files);
      if (localPath) {
        event.preventDefault();
        event.stopPropagation();
        onNavigate(localPath);
      }
    };
    ref.addEventListener("click", onClick, true);
    return () => ref.removeEventListener("click", onClick, true);
  }, [filePath, files, onNavigate, state.kind, bilingual]);

  const toggleAll = useCallback(() => {
    if (!containerRef.current) return;
    const zhBlocks = containerRef.current.querySelectorAll(
      'details[data-zh-translation="true"]',
    );
    const newState = !allExpanded;
    zhBlocks.forEach((d) => {
      (d as HTMLDetailsElement).open = newState;
    });
    setAllExpanded(newState);
  }, [allExpanded]);

  if (state.kind === "loading" || bilingualLoading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-[12px] text-[var(--muted-foreground)]">
        <Loader2 size={14} className="animate-spin" />
        <span>{t("Loading preview…")}</span>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-[12px] text-[var(--muted-foreground)]">
        {state.message}
      </div>
    );
  }

  // Structured bilingual rendering: each group is EN content (native render)
  // followed by a <details> ZH panel when ZH content exists.
  if (hasStructuredBilingual && bilingual) {
    const zhGroups = bilingual.groups.filter(
      (g) => g.zh_content && g.zh_content.trim(),
    );
    return (
      <div className="relative">
        {zhGroups.length > 0 && (
          <div className="sticky top-0 z-10 flex items-center justify-end gap-2 border-b border-[var(--border)] bg-[var(--background)]/90 px-6 py-2 backdrop-blur-sm">
            <button
              type="button"
              onClick={toggleAll}
              className="flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-1 text-[11.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
            >
              {allExpanded ? (
                <>
                  <ChevronUp size={13} strokeWidth={1.7} />
                  <span>收起全部中文</span>
                </>
              ) : (
                <>
                  <ChevronDown size={13} strokeWidth={1.7} />
                  <span>展开全部中文 ({zhGroups.length})</span>
                </>
              )}
            </button>
          </div>
        )}
        <div ref={containerRef} className="mx-auto max-w-4xl px-8 py-8">
          {bilingual.groups.map((group) => (
            <BilingualGroupItem key={group.group_id} group={group} />
          ))}
        </div>
        {dict.popover && (
          <DictionaryPanel
            word={dict.popover.word}
            anchor={dict.popover.anchor}
            loading={dict.loading}
            result={dict.result}
            onLookup={dict.onLookup}
            onTranslate={dict.onTranslate}
            onClose={dict.close}
          />
        )}
      </div>
    );
  }

  // Fallback: legacy markdown rendering (handles en_only, zh_only, and
  // old inline <details> files from the previous bilingual_merger approach).
  return (
    <div className="relative">
      {zhCount > 0 && (
        <div className="sticky top-0 z-10 flex items-center justify-end gap-2 border-b border-[var(--border)] bg-[var(--background)]/90 px-6 py-2 backdrop-blur-sm">
          <button
            type="button"
            onClick={toggleAll}
            className="flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-3 py-1 text-[11.5px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
          >
            {allExpanded ? (
              <>
                <ChevronUp size={13} strokeWidth={1.7} />
                <span>收起全部中文</span>
              </>
            ) : (
              <>
                <ChevronDown size={13} strokeWidth={1.7} />
                <span>展开全部中文 ({zhCount})</span>
              </>
            )}
          </button>
        </div>
      )}
      <div ref={containerRef} className="mx-auto max-w-4xl px-8 py-8">
        <MarkdownRenderer content={state.text} variant="prose" allowHtml />
      </div>
      {dict.popover && (
        <DictionaryPanel
          word={dict.popover.word}
          anchor={dict.popover.anchor}
          loading={dict.loading}
          result={dict.result}
          onLookup={dict.onLookup}
          onTranslate={dict.onTranslate}
          onClose={dict.close}
        />
      )}
    </div>
  );
}
