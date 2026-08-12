"use client";

import { useEffect, useState } from "react";
import {
  Loader2,
  Network,
  RefreshCw,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import Mermaid from "@/components/Mermaid";
import { bookApi } from "@/lib/book-api";
import type {
  Book,
  CharacterGraph,
  CharacterNode,
  Page,
} from "@/lib/book-types";

export interface CharacterGraphPanelProps {
  book: Book | null;
  page: Page | null;
  open: boolean;
  onClose: () => void;
}

type ScopeMode = "current" | "through_current";

export default function CharacterGraphPanel({
  book,
  page,
  open,
  onClose,
}: CharacterGraphPanelProps) {
  const { t } = useTranslation();
  const [graph, setGraph] = useState<CharacterGraph | null>(null);
  const [mermaid, setMermaid] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scope, setScope] = useState<ScopeMode>("current");

  const chapterId = page?.chapter_id || "";

  useEffect(() => {
    if (!open || !book || !chapterId) return;
    let cancelled = false;
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await bookApi.characterGraph(book.id, chapterId, scope);
        if (!cancelled) {
          setGraph(result.graph);
          setMermaid(result.mermaid);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : t("Failed to generate graph"),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [book?.id, chapterId, scope, open, t]);

  async function handleRefresh() {
    if (!book || !chapterId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await bookApi.characterGraph(
        book.id,
        chapterId,
        scope,
        true,
      );
      setGraph(result.graph);
      setMermaid(result.mermaid);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("Failed to generate graph"),
      );
    } finally {
      setLoading(false);
    }
  }

  if (!open) return null;

  return (
    <aside
      className="relative flex h-full shrink-0 flex-col border-l border-[var(--border)] bg-[var(--card)]/40 backdrop-blur"
      style={{ width: 420 }}
    >
      <div
        role="separator"
        aria-orientation="vertical"
        title={t("Drag to resize")}
        className="absolute inset-y-0 left-0 z-10 w-1 cursor-col-resize bg-transparent transition-colors hover:bg-[var(--primary)]/30"
      />
      <header className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
            <Network className="h-4 w-4 text-[var(--primary)]" />
            {t("Character Relationships")}
          </div>
          {page?.title && (
            <div className="mt-1 truncate text-[11px] text-[var(--muted-foreground)]">
              {t("Chapter")}: {page.title}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)] hover:text-[var(--foreground)]"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-2">
        <div className="flex rounded-lg border border-[var(--border)] bg-[var(--background)] p-0.5">
          {(["current", "through_current"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setScope(mode)}
              className={
                scope === mode
                  ? "rounded-md bg-[var(--primary)] px-3 py-1 text-xs font-medium text-[var(--primary-foreground)]"
                  : "rounded-md px-3 py-1 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }
            >
              {mode === "current"
                ? t("Current chapter")
                : t("Through current")}
            </button>
          ))}
        </div>
        <button
          onClick={handleRefresh}
          disabled={loading || !book || !chapterId}
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50"
          title={t("Regenerate")}
          aria-label={t("Regenerate")}
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {loading && !mermaid ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 className="mr-2 h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
            <span className="text-sm text-[var(--muted-foreground)]">
              {t("Extracting characters...")}
            </span>
          </div>
        ) : error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-600">
            {error}
          </div>
        ) : mermaid ? (
          <div>
            <Mermaid chart={mermaid} />
            {graph && graph.nodes.length > 0 && (
              <div className="mt-4 space-y-2">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                  {t("Characters")} ({graph.nodes.length})
                </h4>
                <div className="space-y-1.5">
                  {graph.nodes.map((node: CharacterNode) => (
                    <div
                      key={node.id}
                      className="rounded-lg border border-[var(--border)] bg-[var(--background)]/50 px-3 py-2"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-[var(--foreground)]">
                          {node.name}
                        </span>
                        {node.aliases.length > 0 && (
                          <span className="text-[11px] text-[var(--muted-foreground)]">
                            ({node.aliases.join(", ")})
                          </span>
                        )}
                      </div>
                      {node.description && (
                        <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                          {node.description}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="flex h-40 items-center justify-center text-sm text-[var(--muted-foreground)]">
            {t("No character graph available.")}
          </div>
        )}
      </div>
    </aside>
  );
}
