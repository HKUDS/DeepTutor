"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCcw, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  getDescriptionIndexStatus,
  getDescriptionSearchCapabilities,
  rebuildDescriptionIndex,
  searchReadingMaterial,
  type DescriptionIndexStatus,
  type DescriptionSearchCapabilities,
  type ReadingSearchHit,
  type ReadingSearchMode,
  type ReadingSearchResponse,
  type UnitKind,
} from "@/lib/reading-api";
import { unitLabel } from "./TextUnitView";

export interface ReadingSearchPanelProps {
  materialId: string;
  unit: UnitKind;
  onJump: (locator: number, quote?: string) => void;
  onClose: () => void;
  onError: (message: string) => void;
}

const MODES: Array<{ value: ReadingSearchMode; label: string }> = [
  { value: "exact", label: "Exact" },
  { value: "description_fast", label: "Description · Fast" },
  { value: "description_fine", label: "Description · Fine" },
];

export function ReadingSearchPanel({
  materialId,
  unit,
  onJump,
  onClose,
  onError,
}: ReadingSearchPanelProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<ReadingSearchMode>("exact");
  const [capabilities, setCapabilities] =
    useState<DescriptionSearchCapabilities | null>(null);
  const [index, setIndex] = useState<DescriptionIndexStatus | null>(null);
  const [response, setResponse] = useState<ReadingSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);

  const refreshStatus = useCallback(async () => {
    const [capabilityResult, indexResult] = await Promise.allSettled([
      getDescriptionSearchCapabilities(materialId),
      getDescriptionIndexStatus(materialId),
    ]);
    setCapabilities(
      capabilityResult.status === "fulfilled"
        ? capabilityResult.value
        : {
            model: "",
            binding: "",
            context_window: 0,
            enabled: false,
            minimum_context_window: 50_000,
          },
    );
    if (indexResult.status === "rejected") throw indexResult.reason;
    setIndex(indexResult.value);
  }, [materialId]);

  useEffect(() => {
    let cancelled = false;
    void refreshStatus().catch((error) => {
      if (!cancelled)
        onError(
          error instanceof Error
            ? error.message
            : t("Could not load search status."),
        );
    });
    return () => {
      cancelled = true;
    };
  }, [onError, refreshStatus, t]);

  useEffect(() => {
    if (index?.status !== "building") return;
    const timer = window.setInterval(() => {
      void getDescriptionIndexStatus(materialId)
        .then(setIndex)
        .catch(() => undefined);
    }, 1800);
    return () => window.clearInterval(timer);
  }, [index?.status, materialId]);

  const runSearch = useCallback(
    async (event?: FormEvent) => {
      event?.preventDefault();
      const needle = query.trim();
      if (!needle || loading) return;
      setLoading(true);
      try {
        const result = await searchReadingMaterial(materialId, needle, mode);
        setResponse(result);
        if (result.warnings?.length) {
          onError(
            t(
              "Some candidate chapters could not be searched; the available matches are shown.",
            ),
          );
        }
      } catch (error) {
        onError(
          error instanceof Error
            ? error.message
            : t("Search could not be completed."),
        );
      } finally {
        setLoading(false);
      }
    },
    [loading, materialId, mode, onError, query, t],
  );

  const rebuild = useCallback(async () => {
    if (rebuilding) return;
    setRebuilding(true);
    try {
      setIndex(await rebuildDescriptionIndex(materialId));
    } catch (error) {
      onError(
        error instanceof Error
          ? error.message
          : t("Search index could not be rebuilt."),
      );
    } finally {
      setRebuilding(false);
    }
  }, [materialId, onError, rebuilding, t]);

  const descriptionDisabled = !capabilities?.enabled;

  return (
    <aside className="flex w-[min(360px,44vw)] min-w-[280px] shrink-0 flex-col border-l border-[var(--border)] bg-[var(--background)]">
      <div className="flex h-11 items-center gap-2 border-b border-[var(--border)] px-3">
        <Search size={14} className="text-[var(--muted-foreground)]" />
        <span className="flex-1 text-[12.5px] font-medium">
          {t("Search this book")}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("Close search")}
          className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <X size={14} />
        </button>
      </div>

      <form
        onSubmit={(event) => void runSearch(event)}
        className="border-b border-[var(--border)] p-3"
      >
        <div className="flex gap-1.5">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("Search words, events, people, or ideas…")}
            aria-label={t("Search this book")}
            className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-[12px] outline-none focus:border-[var(--primary)]"
          />
          <button
            type="submit"
            disabled={!query.trim() || loading}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)] disabled:opacity-40"
            aria-label={t("Search")}
          >
            {loading ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Search size={14} />
            )}
          </button>
        </div>

        <div className="mt-2 flex flex-wrap gap-1">
          {MODES.map((item) => {
            const semantic = item.value !== "exact";
            const disabled = semantic && descriptionDisabled;
            return (
              <button
                key={item.value}
                type="button"
                disabled={disabled}
                title={
                  disabled
                    ? t(
                        "Description search needs a model context window of at least 50k.",
                      )
                    : t(item.label)
                }
                onClick={() => setMode(item.value)}
                className={`rounded-md px-2 py-1 text-[10.5px] transition disabled:cursor-not-allowed disabled:opacity-35 ${
                  mode === item.value
                    ? "bg-[var(--primary)]/14 text-[var(--primary)]"
                    : "bg-[var(--muted)]/60 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                {t(item.label)}
              </button>
            );
          })}
        </div>

        {capabilities && !capabilities.enabled && (
          <p className="mt-2 text-[10.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Description search is unavailable: the current model has a {{count}}-token context window; 50k is required.",
              {
                count: capabilities.context_window,
              },
            )}
          </p>
        )}

        {capabilities?.enabled && index && (
          <div className="mt-2 flex items-center gap-2 text-[10.5px] text-[var(--muted-foreground)]">
            {index.status === "building" && (
              <Loader2 size={11} className="animate-spin" />
            )}
            <span className="flex-1">
              {t("Fast index: {{status}} · {{done}}/{{total}} groups", {
                status: t(index.status),
                done: index.completed_groups,
                total: index.total_groups,
              })}
            </span>
            <button
              type="button"
              disabled={rebuilding || index.status === "building"}
              onClick={() => void rebuild()}
              title={t("Rebuild fast index")}
              aria-label={t("Rebuild fast index")}
              className="inline-flex h-6 w-6 items-center justify-center rounded-md hover:bg-[var(--muted)] disabled:opacity-35"
            >
              <RefreshCcw
                size={11}
                className={rebuilding ? "animate-spin" : ""}
              />
            </button>
          </div>
        )}
      </form>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {response?.fallback_used && (
          <div className="mb-2 rounded-lg border border-amber-500/25 bg-amber-500/[0.07] px-2.5 py-2 text-[10.5px] leading-relaxed text-amber-700 dark:text-amber-300">
            {t(
              "Fast search had low confidence, so Fine search was used automatically.",
            )}
          </div>
        )}
        {response && response.hits.length === 0 && !loading && (
          <p className="px-2 py-8 text-center text-[11px] text-[var(--muted-foreground)]">
            {t("No matching passage was found.")}
          </p>
        )}
        <div className="space-y-1.5">
          {response?.hits.map((hit, index) => (
            <SearchResult
              key={`${hit.locator}-${hit.start_offset}-${index}`}
              hit={hit}
              unit={unit}
              onClick={() => onJump(hit.locator, hit.quote || undefined)}
            />
          ))}
        </div>
      </div>
    </aside>
  );
}

function SearchResult({
  hit,
  unit,
  onClick,
}: {
  hit: ReadingSearchHit;
  unit: UnitKind;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onClick}
      className="block w-full rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-left transition hover:border-[var(--primary)]/45 hover:bg-[var(--muted)]/40"
    >
      <span className="flex items-center gap-2 text-[10px] text-[var(--muted-foreground)]">
        <span>
          {t("{{unit}} {{n}}", { unit: t(unitLabel(unit)), n: hit.locator })}
        </span>
        {hit.group_title && (
          <span className="min-w-0 flex-1 truncate">{hit.group_title}</span>
        )}
        {hit.score < 1 && <span>{Math.round(hit.score * 100)}%</span>}
      </span>
      <span className="mt-1.5 line-clamp-4 block text-[11.5px] leading-relaxed text-[var(--foreground)]">
        {hit.snippet}
      </span>
      {hit.reason && (
        <span className="mt-1.5 line-clamp-2 block text-[10.5px] leading-relaxed text-[var(--muted-foreground)]">
          {hit.reason}
        </span>
      )}
    </button>
  );
}
