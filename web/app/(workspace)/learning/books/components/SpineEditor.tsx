"use client";

import {
  ArrowDown,
  ArrowUp,
  Blocks,
  ChevronDown,
  Plus,
  Trash2,
  CheckCircle2,
  Clock3,
  FileText,
  Layers,
  Loader2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { bookApi, type EstimateBasis } from "@/lib/book-api";
import type { BookDepth, Chapter, ContentType, Spine } from "@/lib/book-types";
import Tooltip from "@/shared/ui/Tooltip";

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

/**
 * The one block type the reader cannot switch off.
 *
 * `section` carries the chapter's prose; a chapter without it is a chapter
 * with no text in it. The backend enforces this too — the picker just does
 * not offer it, rather than offering it and refusing.
 */
const ALWAYS_ON_TYPE = "section";

interface BlockTypeOption {
  value: string;
  planner_default: boolean;
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
      className={`rounded-[7px] px-2.5 py-1 font-medium transition-colors ${
        active
          ? "bg-[var(--background)] text-[var(--foreground)] shadow-[0_0_0_1px_rgb(15_15_15/0.04),0_1px_2px_rgb(15_15_15/0.08)]"
          : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
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
  onConfirm: (
    spine: Spine,
    autoCompile: boolean,
    /** `null` when the picker never loaded — leave the book's choice alone. */
    blockTypes: string[] | null,
  ) => void | Promise<void>;
  loading?: boolean;
  /** Book depth, so the estimate matches what will actually be generated. */
  depth?: BookDepth;
  /** The book's current block-type choice, if it already has one. */
  initialBlockTypes?: string[];
}

export default function SpineEditor({
  spine,
  onConfirm,
  loading = false,
  depth = "standard",
  initialBlockTypes,
}: SpineEditorProps) {
  const { t } = useTranslation();
  // Engine-injected chapters (the overview, deep-dive sub-pages) are not part
  // of the structure the reader authors, so they stay out of the editor.
  const [chapters, setChapters] = useState<Chapter[]>(() =>
    spine.chapters.filter((c) => !c.auto_overview && !c.deep_dive),
  );
  const [autoCompile, setAutoCompile] = useState(true);
  /**
   * Which kinds of content the chapters may contain.
   *
   * `null` until the planner's own list arrives — the web app must not keep a
   * second copy of what the architect can plan, or the two drift and the
   * reader is offered a type that never appears (or denied one that does).
   */
  const [blockTypes, setBlockTypes] = useState<string[] | null>(null);
  const [typeCatalog, setTypeCatalog] = useState<BlockTypeOption[]>([]);
  const [typesOpen, setTypesOpen] = useState(false);
  const typesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    bookApi
      .blockTypes()
      .then(({ block_types }) => {
        if (cancelled) return;
        const catalog = block_types.filter(
          (option) => option.value !== ALWAYS_ON_TYPE,
        );
        setTypeCatalog(catalog);
        setBlockTypes((current) => {
          if (current) return current;
          if (initialBlockTypes?.length) {
            return catalog
              .filter((option) => initialBlockTypes.includes(option.value))
              .map((option) => option.value);
          }
          // Everything the templates already use, which is what a book
          // generated today contains.
          return catalog
            .filter((option) => option.planner_default)
            .map((option) => option.value);
        });
      })
      .catch(() => {
        // Without the list the picker simply does not appear; confirming
        // sends no restriction, which is exactly today's behaviour.
      });
    return () => {
      cancelled = true;
    };
  }, [initialBlockTypes]);

  useEffect(() => {
    if (!typesOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!typesRef.current?.contains(event.target as Node)) {
        setTypesOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setTypesOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [typesOpen]);
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
    // `section` is implied by the backend and is not the reader's to drop:
    // it is the chapter's prose.
    await onConfirm(
      { ...spine, chapters: merged },
      autoCompile,
      blockTypes ? [ALWAYS_ON_TYPE, ...blockTypes] : null,
    );
  };

  return (
    <div className="flex h-full flex-col">
      <header className="mx-auto w-full max-w-3xl px-6 pb-2 pt-6">
        <h2 className="text-[18px] font-semibold tracking-[-0.01em] text-[var(--foreground)]">
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
            <div key={chapter.id} className="dt-soft-card group/chapter">
              <div className="flex items-center justify-between gap-2">
                <span className="w-6 shrink-0 text-center text-[12px] font-medium tabular-nums text-[var(--muted-foreground)]">
                  {idx + 1}
                </span>
                <input
                  value={chapter.title}
                  onChange={(e) =>
                    updateChapter(idx, { title: e.target.value })
                  }
                  aria-label={t("Chapter title")}
                  className="min-w-0 flex-1 rounded-lg bg-transparent px-2 py-1 text-[15px] font-semibold text-[var(--foreground)] outline-none transition-colors hover:bg-[var(--background)] focus:bg-[var(--background)] focus:shadow-[0_0_0_1px_color-mix(in_srgb,var(--primary)_45%,transparent)]"
                />
                <div className="flex items-center gap-0.5 opacity-60 transition-opacity group-hover/chapter:opacity-100 group-focus-within/chapter:opacity-100">
                  <button
                    onClick={() => move(idx, -1)}
                    disabled={idx === 0}
                    aria-label={t("Move up")}
                    className="dt-quiet-button is-icon !size-7 disabled:pointer-events-none disabled:opacity-30"
                  >
                    <ArrowUp className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => move(idx, 1)}
                    disabled={idx === chapters.length - 1}
                    aria-label={t("Move down")}
                    className="dt-quiet-button is-icon !size-7 disabled:pointer-events-none disabled:opacity-30"
                  >
                    <ArrowDown className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => remove(idx)}
                    aria-label={t("Remove chapter")}
                    className="dt-quiet-button is-icon !size-7 hover:!bg-rose-500/10 hover:!text-rose-600"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              <div className="mt-3 grid gap-3 pl-8 sm:grid-cols-2">
                <label className="text-xs text-[var(--muted-foreground)]">
                  <span className="flex items-center gap-1">
                    {t("Content type")}
                    <Tooltip
                      label={t(
                        "Hint that drives the chapter's block plan (text length, whether to include diagrams / quizzes / code, etc.).",
                      )}
                    >
                      <span
                        tabIndex={0}
                        role="note"
                        className="cursor-help text-[10px] opacity-60"
                      >
                        ⓘ
                      </span>
                    </Tooltip>
                  </span>
                  <select
                    value={chapter.content_type}
                    onChange={(e) =>
                      updateChapter(idx, {
                        content_type: e.target.value as ContentType,
                      })
                    }
                    className="dt-soft-input mt-1 w-full rounded-lg bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)] outline-none"
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
                    className="dt-soft-input mt-1 w-full rounded-lg bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)] outline-none"
                  />
                </label>
              </div>

              <label className="mt-3 block pl-8 text-xs text-[var(--muted-foreground)]">
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
                  className="dt-soft-input mt-1 w-full resize-none rounded-lg bg-[var(--background)] px-2.5 py-1.5 text-sm text-[var(--foreground)] outline-none"
                />
              </label>
            </div>
          ))}

          <button
            onClick={addChapter}
            className="inline-flex items-center justify-center gap-1.5 rounded-[14px] px-3 py-2.5 text-sm font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
          >
            <Plus className="h-4 w-4" /> {t("Add chapter")}
          </button>
        </div>
      </div>

      <footer className="px-6 pb-4 pt-2">
        <div className="dt-floating-bar mx-auto flex w-full max-w-3xl flex-wrap items-center justify-between gap-3">
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
            {/* What goes *in* a chapter, beside how many chapters. Both
                answer "what will be generated", and each block type is a
                model call per chapter — so leaving a kind out is how a
                reader controls both the shape and the cost of the book. */}
            {blockTypes && typeCatalog.length > 0 && (
              <div className="relative" ref={typesRef}>
                <button
                  type="button"
                  onClick={() => setTypesOpen((current) => !current)}
                  aria-expanded={typesOpen}
                  className="dt-quiet-button !h-8 !gap-1.5 !px-2.5 !text-[11.5px] font-medium"
                >
                  <Blocks className="h-3 w-3" />
                  {blockTypes.length === typeCatalog.length
                    ? t("All content types")
                    : t("{{count}} content types", {
                        count: blockTypes.length + 1,
                      })}
                  <ChevronDown
                    className={`h-3 w-3 transition-transform ${
                      typesOpen ? "rotate-180" : ""
                    }`}
                  />
                </button>
                {typesOpen && (
                  <div className="dt-detail-in absolute bottom-full right-0 z-40 mb-1.5 w-64 rounded-xl border border-[var(--border)] bg-[var(--card)] p-2 shadow-lg">
                    <p className="px-1.5 pb-1.5 text-[11px] leading-snug text-[var(--muted-foreground)]">
                      {t(
                        "Kinds of content the chapters may contain. Each one is a separate model call per chapter.",
                      )}
                    </p>
                    <ul className="max-h-64 overflow-y-auto">
                      <li className="flex items-center gap-2 rounded-md px-1.5 py-1 text-[12px] text-[var(--muted-foreground)]">
                        <input
                          type="checkbox"
                          checked
                          disabled
                          className="h-3.5 w-3.5 accent-[var(--primary)]"
                        />
                        <span className="text-[var(--foreground)]">
                          {t(ALWAYS_ON_TYPE)}
                        </span>
                        <span className="ml-auto text-[10.5px] opacity-70">
                          {t("always")}
                        </span>
                      </li>
                      {typeCatalog.map((option) => {
                        const on = blockTypes.includes(option.value);
                        return (
                          <li key={option.value}>
                            <label className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-[12px] hover:bg-[var(--muted)]">
                              <input
                                type="checkbox"
                                checked={on}
                                onChange={() =>
                                  setBlockTypes((current) =>
                                    (current || []).includes(option.value)
                                      ? (current || []).filter(
                                          (value) => value !== option.value,
                                        )
                                      : [...(current || []), option.value],
                                  )
                                }
                                className="h-3.5 w-3.5 accent-[var(--primary)]"
                              />
                              <span className="text-[var(--foreground)]">
                                {t(option.value)}
                              </span>
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                    <div className="mt-1 flex items-center justify-between pt-1">
                      <button
                        type="button"
                        onClick={() =>
                          setBlockTypes(
                            typeCatalog.map((option) => option.value),
                          )
                        }
                        className="rounded-md px-1.5 py-1 text-[11px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                      >
                        {t("Select all")}
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setBlockTypes(
                            typeCatalog
                              .filter((option) => option.planner_default)
                              .map((option) => option.value),
                          )
                        }
                        className="rounded-md px-1.5 py-1 text-[11px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                      >
                        {t("Reset to default")}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
            <div className="inline-flex rounded-[9px] bg-[rgb(var(--dt-ink,55_53_47)/0.06)] p-[3px] text-[11px]">
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
            {/* One label for both scopes. Swapping it between "Confirm spine
                & start compiling" and "Confirm spine" resized the button and
                shoved the scope control sideways, so picking a scope moved
                the thing you had just picked. */}
            <button
              onClick={handleConfirm}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
              {t("Confirm spine")}
            </button>
          </div>
        </div>
        {/* Always rendered, one line high, so the scope control does not sit
            on a footer that grows and shrinks under it. Each scope says what
            it costs — that is the whole reason to offer the choice. */}
        <p className="mx-auto mt-2 min-h-[1.25rem] w-full max-w-3xl px-4 text-[11px] leading-5 text-[var(--muted-foreground)]">
          {autoCompile
            ? t(
                "Every chapter is written now, in order. You can read the first one while the rest are still coming.",
              )
            : t(
                "Chapters will be generated the first time you open them — useful when you want to read as you go, or keep an eye on model usage.",
              )}
        </p>
      </footer>
    </div>
  );
}
