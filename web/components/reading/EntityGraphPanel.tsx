"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Network, RotateCcw, TriangleAlert, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Mermaid } from "@/components/Mermaid";
import {
  fetchEntityGraph,
  type EntityGraphResult,
  type EntityGraphScope,
  type UnitKind,
} from "@/lib/reading-api";
import { unitLabel } from "./TextUnitView";

interface EntityGraphPanelProps {
  materialId: string;
  materialUnit: UnitKind;
  locator: number;
  onClose: () => void;
}

export function EntityGraphPanel({
  materialId,
  materialUnit,
  locator,
  onClose,
}: EntityGraphPanelProps) {
  const { t } = useTranslation();
  const [scope, setScope] = useState<EntityGraphScope>("current");
  const [graph, setGraph] = useState<EntityGraphResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef(0);

  const load = useCallback(
    async (forceRefresh: boolean) => {
      const request = ++requestRef.current;
      setLoading(true);
      setError(null);
      setGraph(null);
      try {
        const result = await fetchEntityGraph(
          materialId,
          locator,
          scope,
          forceRefresh,
        );
        if (requestRef.current === request) setGraph(result);
      } catch (cause) {
        if (requestRef.current === request) {
          setGraph(null);
          setError(
            cause instanceof Error
              ? cause.message
              : t("Failed to generate relationship graph"),
          );
        }
      } finally {
        if (requestRef.current === request) setLoading(false);
      }
    },
    [materialId, locator, scope, t],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  const nodeName = useCallback((id: string) => {
    const node = graph?.graph.nodes.find((candidate) => candidate.id === id);
    return node?.name ?? id;
  }, [graph]);

  const unitWord = t(unitLabel(materialUnit));
  const included =
    graph?.included_locators.map((value) => `${unitWord} ${value}`).join(", ") ??
    `${unitWord} ${locator}`;

  return (
    <aside className="absolute inset-y-0 right-0 z-30 flex w-[min(100%,390px)] flex-col border-l border-[var(--border)] bg-[var(--background)] shadow-xl">
      <header className="flex h-10 shrink-0 items-center gap-2 border-b border-[var(--border)] px-3">
        <Network size={14} className="text-[var(--primary)]" />
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium">
          {t("Relationship graph")}
        </span>
        <button
          type="button"
          title={t("Refresh")}
          aria-label={t("Refresh")}
          disabled={loading}
          onClick={() => void load(true)}
          className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-50"
        >
          {loading ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <RotateCcw size={14} />
          )}
        </button>
        <button
          type="button"
          title={t("Close")}
          aria-label={t("Close")}
          onClick={onClose}
          className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <X size={14} />
        </button>
      </header>

      <div
        role="group"
        aria-label={t("Graph scope")}
        className="flex shrink-0 gap-1 border-b border-[var(--border)] p-2"
      >
        {(
          [
            ["current", t("Current unit")],
            ["through_current", t("Through current unit")],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={scope === value}
            onClick={() => setScope(value)}
            className={`h-7 flex-1 rounded-md px-2 text-[11.5px] font-medium transition ${
              scope === value
                ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <p className="shrink-0 border-b border-[var(--border)] px-3 py-2 text-[11px] text-[var(--muted-foreground)]">
        {included}
      </p>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {error ? (
          <div className="flex items-start gap-2 border border-[var(--destructive)]/25 bg-[var(--destructive)]/[0.06] p-3 text-[12px] leading-relaxed text-[var(--destructive)]">
            <TriangleAlert size={14} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        ) : loading && !graph ? (
          <div className="flex items-center justify-center gap-2 py-10 text-[12px] text-[var(--muted-foreground)]">
            <Loader2 size={14} className="animate-spin" />
            {t("Generating relationship graph…")}
          </div>
        ) : !graph || graph.graph.nodes.length === 0 ? (
          <div className="py-10 text-center text-[12px] text-[var(--muted-foreground)]">
            {t("No supported entities were found in this scope.")}
          </div>
        ) : (
          <div className="space-y-4">
            {graph.truncated && (
              <p className="border border-amber-500/30 bg-amber-500/10 p-2 text-[11px] leading-relaxed text-amber-800 dark:text-amber-200">
                {t(
                  "The source range was too long, so the graph uses the earliest units plus the current unit.",
                )}
              </p>
            )}
            <div className="-mx-1 overflow-x-auto">
              <Mermaid chart={graph.mermaid} className="!my-0" />
            </div>

            <section>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                {t("Entities")}
              </h3>
              <div className="space-y-2">
                {graph.graph.nodes.map((node) => (
                  <article
                    key={node.id}
                    className="border border-[var(--border)] p-2.5"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="min-w-0 truncate text-[12.5px] font-medium">
                        {node.name}
                      </p>
                      <span className="shrink-0 font-mono text-[10px] tabular-nums text-[var(--muted-foreground)]">
                        {Math.round(node.confidence * 100)}%
                      </span>
                    </div>
                    {node.aliases.length > 0 && (
                      <p className="mt-1 truncate text-[11px] text-[var(--muted-foreground)]">
                        {t("Also known as")}: {node.aliases.join(", ")}
                      </p>
                    )}
                    {node.description && (
                      <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
                        {node.description}
                      </p>
                    )}
                  </article>
                ))}
              </div>
            </section>

            <section>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                {t("Relationships")}
              </h3>
              <div className="space-y-2">
                {graph.graph.edges.map((edge) => (
                  <article
                    key={`${edge.source}-${edge.target}-${edge.relation}`}
                    className="border border-[var(--border)] p-2.5"
                  >
                    <p className="text-[12px] font-medium">
                      {nodeName(edge.source)} · {edge.relation} ·{" "}
                      {nodeName(edge.target)}
                    </p>
                    <blockquote className="mt-1.5 border-l-2 border-[var(--border)] pl-2 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
                      {edge.evidence}
                    </blockquote>
                    <p className="mt-1.5 font-mono text-[10px] text-[var(--muted-foreground)]">
                      {edge.evidence_locators
                        .map((value) => `${unitWord} ${value}`)
                        .join(", ")}
                    </p>
                  </article>
                ))}
              </div>
            </section>
          </div>
        )}
      </div>
    </aside>
  );
}
