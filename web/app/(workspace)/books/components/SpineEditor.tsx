"use client";

import {
  ArrowDown,
  ArrowUp,
  Plus,
  Trash2,
  CheckCircle2,
  Clock3,
  FileText,
  Layers,
  Loader2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { bookApi, type EstimateBasis } from "@/lib/book-api";
import type { BookDepth, Chapter, ContentType, Spine } from "@/lib/book-types";

/**
 * Each chapter declares a *content type* — a hint to the SectionArchitect
 * about what kind of block sequence to plan (e.g. theory chapters get
 * Section + Figure + Quiz; practice chapters get more Quiz + Code).
 *
 * `overview` is intentionally excluded — it's reserved for the engine-injected
 * first chapter (the table of contents + concept map).
 */
interface ContentTypeOption {
  value: ContentType;
  label: string;
  description: string;
}

function ScopeOption({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`px-2.5 py-1.5 font-medium transition-colors ${
        active
          ? "bg-[var(--primary)]/12 text-[var(--foreground)]"
          : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40 hover:text-[var(--foreground)]"
      }`}
    >
      {label}
    </button>
  );
}

const CONTENT_TYPE_OPTIONS: ContentTypeOption[] = [
  {
    value: "theory",
    label: "Theory",
    description: "Long-form explanation with diagrams + flash cards + a quiz.",
  },
  {
    value: "derivation",
    label: "Derivation",
    description:
      "Step-by-step derivation, often with animation + verifying code.",
  },
  {
    value: "history",
    label: "History",
    description: "Narrative + timeline + period image, ends with a recap quiz.",
  },
  {
    value: "practice",
    label: "Practice",
    description:
      "Quiz-heavy chapter with a runnable code scaffold + explanation.",
  },
  {
    value: "concept",
    label: "Concept",
    description: "Definition + figure + flash cards + common-pitfall callout.",
  },
];

export interface SpineEditorProps {
  spine: Spine;
  onConfirm: (spine: Spine, autoCompile: boolean) => void | Promise<void>;
  loading?: boolean;
  /** Book depth, so the estimate matches what will actually be generated. */
  depth?: BookDepth;
}

export default function SpineEditor({
  spine,
  onConfirm,
  loading = false,
  depth = "standard",
}: SpineEditorProps) {
  const { t } = useTranslation();
  // Engine-injected chapters (the overview, deep-dive sub-pages) are not part
  // of the structure the reader authors, so they stay out of the editor.
  const [chapters, setChapters] = useState<Chapter[]>(() =>
    spine.chapters.filter((c) => !c.auto_overview && !c.deep_dive),
  );
  const [autoCompile, setAutoCompile] = useState(true);
  const [basis, setBasis] = useState<EstimateBasis | null>(null);

  useEffect(() => {
    let cancelled = false;
    void bookApi
      .estimateBasis(depth)
      .then((result) => {
        if (!cancelled) setBasis(result.basis);
      })
      .catch(() => {
        // An estimate is a courtesy; its absence must not block confirming.
      });
    return () => {
      cancelled = true;
    };
  }, [depth]);

  const estimate = useMemo(() => {
    if (!basis) return null;
    let words = 0;
    let seconds = 0;
    for (const chapter of chapters) {
      const cost = basis[chapter.content_type] || basis.theory;
      if (!cost) continue;
      words += cost.words;
      seconds += cost.seconds;
    }
    return {
      chapters: chapters.length,
      words,
      minutes: Math.ceil(seconds / 60),
    };
  }, [basis, chapters]);

  const updateChapter = (idx: number, patch: Partial<Chapter>) => {
    setChapters((prev) =>
      prev.map((c, i) => (i === idx ? { ...c, ...patch } : c)),
    );
  };

  const move = (idx: number, dir: -1 | 1) => {
    setChapters((prev) => {
      const next = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[idx], next[target]] = [next[target], next[idx]];
      return next.map((c, i) => ({ ...c, order: i }));
    });
  };

  const remove = (idx: number) => {
    setChapters((prev) =>
      prev.filter((_, i) => i !== idx).map((c, i) => ({ ...c, order: i })),
    );
  };

  const addChapter = () => {
    setChapters((prev) => [
      ...prev,
      {
        id: `ch_new_${prev.length + 1}_${Date.now().toString(36)}`,
        title: t("New chapter"),
        learning_objectives: [],
        content_type: "theory",
        source_anchors: [],
        prerequisites: [],
        page_ids: [],
        summary: "",
        order: prev.length,
      },
    ]);
  };

  const handleConfirm = async () => {
    const edited = chapters.filter((c) => c.title.trim());
    // Re-attach what the editor hid, so confirming never silently deletes an
    // overview or a deep dive — but in their proper places: the overview leads
    // the book, deep dives trail it. Appending everything to the end left the
    // overview out of position and carrying a stale `order`.
    const overview = spine.chapters.filter((c) => c.auto_overview);
    const deepDives = spine.chapters.filter(
      (c) => c.deep_dive && !c.auto_overview,
    );
    const merged = [...overview, ...edited, ...deepDives].map((c, i) => ({
      ...c,
      order: i,
    }));
    await onConfirm({ ...spine, chapters: merged }, autoCompile);
  };

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-[var(--border)] bg-[var(--card)]/60 px-6 py-4">
        <h2 className="text-lg font-semibold text-[var(--foreground)]">
          {t("Review the chapter spine")}
        </h2>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {t(
            "Reorder, rename, or remove chapters before the book starts compiling.",
          )}
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-3">
          {chapters.map((chapter, idx) => (
            <div
              key={chapter.id}
              className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm"
            >
              <div className="flex items-start justify-between gap-2">
                <input
                  value={chapter.title}
                  onChange={(e) =>
                    updateChapter(idx, { title: e.target.value })
                  }
                  className="flex-1 rounded-lg border border-transparent bg-transparent px-2 py-1 text-base font-semibold text-[var(--foreground)] outline-none focus:border-[var(--border)]"
                />
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => move(idx, -1)}
                    disabled={idx === 0}
                    className="rounded-md border border-[var(--border)] p-1 text-[var(--muted-foreground)] disabled:opacity-30"
                  >
                    <ArrowUp className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => move(idx, 1)}
                    disabled={idx === chapters.length - 1}
                    className="rounded-md border border-[var(--border)] p-1 text-[var(--muted-foreground)] disabled:opacity-30"
                  >
                    <ArrowDown className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => remove(idx)}
                    className="rounded-md border border-rose-300/60 p-1 text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-500/10"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <label className="text-xs text-[var(--muted-foreground)]">
                  <span className="flex items-center gap-1">
                    {t("Content type")}
                    <span
                      className="cursor-help text-[10px] opacity-60"
                      title={t(
                        "Hint that drives the chapter's block plan (text length, whether to include diagrams / quizzes / code, etc.).",
                      )}
                    >
                      ⓘ
                    </span>
                  </span>
                  <select
                    value={chapter.content_type}
                    onChange={(e) =>
                      updateChapter(idx, {
                        content_type: e.target.value as ContentType,
                      })
                    }
                    className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-sm text-[var(--foreground)]"
                  >
                    {CONTENT_TYPE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {t(opt.label)}
                      </option>
                    ))}
                  </select>
                  <span className="mt-1 block text-[11px] leading-snug text-[var(--muted-foreground)]/80">
                    {t(
                      CONTENT_TYPE_OPTIONS.find(
                        (o) => o.value === chapter.content_type,
                      )?.description ||
                        "Hint for the architect about what blocks to plan.",
                    )}
                  </span>
                </label>
                <label className="text-xs text-[var(--muted-foreground)]">
                  {t("Summary")}
                  <input
                    value={chapter.summary}
                    onChange={(e) =>
                      updateChapter(idx, { summary: e.target.value })
                    }
                    placeholder={t("Optional one-line description")}
                    className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-sm text-[var(--foreground)]"
                  />
                </label>
              </div>

              <label className="mt-3 block text-xs text-[var(--muted-foreground)]">
                {t("Learning objectives (one per line)")}
                <textarea
                  value={chapter.learning_objectives.join("\n")}
                  onChange={(e) =>
                    updateChapter(idx, {
                      learning_objectives: e.target.value
                        .split("\n")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                  rows={3}
                  className="mt-1 w-full resize-none rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-sm text-[var(--foreground)]"
                />
              </label>
            </div>
          ))}

          <button
            onClick={addChapter}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm font-medium text-[var(--muted-foreground)] hover:border-[var(--primary)]/40 hover:text-[var(--primary)]"
          >
            <Plus className="h-4 w-4" /> {t("Add chapter")}
          </button>
        </div>
      </div>

      <footer className="border-t border-[var(--border)] bg-[var(--card)]/60 px-6 py-3">
        <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center justify-between gap-3">
          {/* Confirming here starts dozens of model calls. Say so first. */}
          <div className="flex items-center gap-3 text-[11px] text-[var(--muted-foreground)]">
            <span className="inline-flex items-center gap-1">
              <Layers className="h-3 w-3" />
              {t("{{count}} chapters", { count: chapters.length })}
            </span>
            {estimate && estimate.words > 0 && (
              <>
                <span className="inline-flex items-center gap-1">
                  <FileText className="h-3 w-3" />
                  {t("~{{count}} words", {
                    count: Math.round(estimate.words / 100) * 100,
                  })}
                </span>
                <span className="inline-flex items-center gap-1">
                  <Clock3 className="h-3 w-3" />
                  {t("~{{count}} min to generate", { count: estimate.minutes })}
                </span>
              </>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* #655: the backend always supported deferring compilation; only
                the UI insisted on building everything up front. */}
            <div className="inline-flex overflow-hidden rounded-lg border border-[var(--border)] text-[11px]">
              <ScopeOption
                active={autoCompile}
                label={t("Generate all chapters")}
                onClick={() => setAutoCompile(true)}
              />
              <ScopeOption
                active={!autoCompile}
                label={t("First chapter only")}
                onClick={() => setAutoCompile(false)}
              />
            </div>
            <button
              onClick={handleConfirm}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              {autoCompile
                ? t("Confirm spine & start compiling")
                : t("Confirm spine")}
            </button>
          </div>
        </div>
        {!autoCompile && (
          <p className="mx-auto mt-2 w-full max-w-3xl text-[11px] text-[var(--muted-foreground)]">
            {t(
              "Chapters will be generated the first time you open them — useful when you want to read as you go, or keep an eye on model usage.",
            )}
          </p>
        )}
      </footer>
    </div>
  );
}
