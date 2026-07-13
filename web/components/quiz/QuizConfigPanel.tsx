"use client";

import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, FileText, Upload, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  summarizeQuizConfig,
  QUIZ_TYPE_LABEL_KEYS,
  type DeepQuestionFormConfig,
  type DeepQuestionMode,
} from "@/lib/quiz-types";
import {
  QUIZ_QUESTION_TYPES,
  type NormalizedQuizQuestionType,
} from "@/lib/quiz-question-type";
import {
  CollapsibleConfigSection,
  Field,
  INPUT_CLS,
} from "@/components/chat/home/composer-field";

interface QuizConfigPanelProps {
  value: DeepQuestionFormConfig;
  onChange: (next: DeepQuestionFormConfig) => void;
  uploadedPdf: File | null;
  onUploadPdf: (file: File | null) => void;
  /**
   * When provided, the panel is wrapped in a `CollapsibleConfigSection` (used
   * by /playground). Omit both to render the bare form — used inside the
   * chat's right-side Activity panel where the parent card supplies its own
   * header.
   */
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
}

// Per-type accent colors. Used both for the filled segment background and
// for the legend dot. Kept inline so Tailwind's JIT picks each class up —
// do NOT compose at runtime.
const TYPE_ACCENT: Record<
  NormalizedQuizQuestionType,
  { fill: string; dot: string }
> = {
  choice: { fill: "bg-orange-500", dot: "bg-orange-500" },
  concept: { fill: "bg-emerald-500", dot: "bg-emerald-500" },
  fill_in_blank: { fill: "bg-sky-500", dot: "bg-sky-500" },
  short_answer: { fill: "bg-violet-500", dot: "bg-violet-500" },
  written: { fill: "bg-rose-500", dot: "bg-rose-500" },
  coding: { fill: "bg-slate-500", dot: "bg-slate-500" },
};

/**
 * Re-distribute the total quiz count across the selected types. Each
 * selected type gets at least 1; remainder lands on the first types in
 * ``types`` order. Existing counts in ``prev`` are preserved when their
 * sum already matches; otherwise we rebuild a clean equal split.
 */
function rebalanceCounts(
  types: NormalizedQuizQuestionType[],
  total: number,
  prev: Partial<Record<NormalizedQuizQuestionType, number>>,
): Partial<Record<NormalizedQuizQuestionType, number>> {
  if (types.length < 2) return {};
  const safeTotal = Math.max(types.length, total);
  // Try to preserve user-set counts if they still sum to safeTotal and
  // each is ≥ 1.
  const preserved: Record<string, number> = {};
  let preservedSum = 0;
  let preservedValid = true;
  for (const t of types) {
    const v = prev[t];
    if (typeof v !== "number" || !Number.isFinite(v) || v < 1) {
      preservedValid = false;
      break;
    }
    preserved[t] = Math.floor(v);
    preservedSum += preserved[t];
  }
  if (preservedValid && preservedSum === safeTotal) {
    return preserved as Partial<Record<NormalizedQuizQuestionType, number>>;
  }
  // Equal split with remainder.
  const base = Math.floor(safeTotal / types.length);
  let remainder = safeTotal - base * types.length;
  const out: Record<string, number> = {};
  for (const t of types) {
    out[t] = base + (remainder > 0 ? 1 : 0);
    if (remainder > 0) remainder -= 1;
  }
  return out as Partial<Record<NormalizedQuizQuestionType, number>>;
}

export default memo(function QuizConfigPanel({
  value,
  onChange,
  uploadedPdf,
  onUploadPdf,
  collapsed,
  onToggleCollapsed,
}: QuizConfigPanelProps) {
  const { t } = useTranslation();
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const update = <K extends keyof DeepQuestionFormConfig>(
    key: K,
    val: DeepQuestionFormConfig[K],
  ) => onChange({ ...value, [key]: val });

  const setMode = (m: DeepQuestionMode) => update("mode", m);

  // Whenever the selected-type set or the total count drifts out of sync
  // with per_type_counts, auto-rebalance so the user never sees a broken
  // intermediate state.
  useEffect(() => {
    if (value.mode !== "custom") return;
    if (value.question_types.length < 2) {
      if (Object.keys(value.per_type_counts).length > 0) {
        onChange({ ...value, per_type_counts: {} });
      }
      return;
    }
    // If the user picks more types than num_questions allows, bump the
    // total so each type can get at least 1.
    let total = value.num_questions;
    if (total < value.question_types.length) {
      total = value.question_types.length;
    }
    const next = rebalanceCounts(
      value.question_types,
      total,
      value.per_type_counts,
    );
    const sameTotal = total === value.num_questions;
    const sameCounts =
      Object.keys(next).length === Object.keys(value.per_type_counts).length &&
      Object.entries(next).every(
        ([k, v]) =>
          value.per_type_counts[k as NormalizedQuizQuestionType] === v,
      );
    if (sameTotal && sameCounts) return;
    onChange({ ...value, num_questions: total, per_type_counts: next });
  }, [value, onChange]);

  const handleTypesChange = (next: NormalizedQuizQuestionType[]) =>
    onChange({ ...value, question_types: next });

  const handleCountsChange = (
    next: Partial<Record<NormalizedQuizQuestionType, number>>,
  ) => onChange({ ...value, per_type_counts: next });

  const showRatioBar =
    value.mode === "custom" && value.question_types.length >= 2;

  const totalCount = value.question_types
    .map((t_) => value.per_type_counts[t_] ?? 0)
    .reduce((sum, n) => sum + n, 0);

  const body = (
    <>
      <div className="grid w-full grid-cols-2 gap-1 rounded-lg border border-[var(--border)]/25 p-0.5">
        {(["custom", "mimic"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={`flex h-[26px] items-center justify-center rounded-md text-[11px] font-medium transition-all ${
              value.mode === m
                ? "bg-[var(--muted)] text-[var(--foreground)] shadow-sm"
                : "text-[var(--muted-foreground)]/50 hover:text-[var(--muted-foreground)]"
            }`}
          >
            {m === "custom" ? t("Custom") : t("Mimic Paper")}
          </button>
        ))}
      </div>

      {value.mode === "custom" ? (
        <div className="space-y-2.5">
          <div className="flex items-end gap-x-2">
            <Field label={t("Count")} width="w-[60px]">
              <input
                type="number"
                min={1}
                max={50}
                value={value.num_questions}
                onChange={(e) =>
                  update(
                    "num_questions",
                    Math.max(1, Number(e.target.value) || 1),
                  )
                }
                className={`${INPUT_CLS} w-full`}
              />
            </Field>

            <Field label={t("Difficulty")} width="flex-1">
              <select
                value={value.difficulty}
                onChange={(e) => update("difficulty", e.target.value)}
                className={`${INPUT_CLS} w-full`}
              >
                <option value="auto">{t("Auto")}</option>
                <option value="easy">{t("Easy")}</option>
                <option value="medium">{t("Medium")}</option>
                <option value="hard">{t("Hard")}</option>
              </select>
            </Field>

            <Field label={t("Type")} width="flex-1">
              <TypeMultiSelect
                value={value.question_types}
                onChange={handleTypesChange}
              />
            </Field>
          </div>

          {showRatioBar && (
            <div className="rounded-lg border border-[var(--border)]/30 bg-[var(--background)]/40 p-2.5">
              <div className="mb-1.5 flex items-center justify-between text-[10px] font-medium text-[var(--muted-foreground)]/60">
                <span>{t("Type Mix")}</span>
                <span className="tabular-nums">
                  {totalCount}/{value.num_questions}
                </span>
              </div>
              <DraggableRatioBar
                types={value.question_types}
                counts={value.per_type_counts}
                total={value.num_questions}
                onChange={handleCountsChange}
              />
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-[var(--muted-foreground)]">
                {value.question_types.map((qt) => {
                  const count = value.per_type_counts[qt] ?? 0;
                  return (
                    <span key={qt} className="inline-flex items-center gap-1.5">
                      <span
                        className={`h-2 w-2 shrink-0 rounded-full ${TYPE_ACCENT[qt].dot}`}
                      />
                      <span className="text-[var(--foreground)]">
                        {t(QUIZ_TYPE_LABEL_KEYS[qt])}
                      </span>
                      <span className="font-semibold tabular-nums text-[var(--foreground)]">
                        {count}
                      </span>
                    </span>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
          <Field label={t("Paper")} width="min-w-[180px] flex-[1.3]">
            {uploadedPdf ? (
              <div className="flex h-[30px] items-center gap-2 rounded-lg border border-[var(--border)]/30 bg-[var(--background)]/50 px-2.5 text-[12px]">
                <FileText
                  size={12}
                  className="shrink-0 text-[var(--primary)]/60"
                />
                <span className="min-w-0 truncate text-[var(--foreground)]">
                  {uploadedPdf.name}
                </span>
                <button
                  type="button"
                  onClick={() => onUploadPdf(null)}
                  className="ml-auto shrink-0 text-[var(--muted-foreground)]/40 transition-colors hover:text-[var(--foreground)]"
                  aria-label={t("Remove PDF")}
                >
                  <X size={11} />
                </button>
              </div>
            ) : (
              <label
                className={`flex h-[30px] cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-dashed px-2.5 text-[12px] transition-colors ${
                  dragOver
                    ? "border-[var(--primary)]/35 text-[var(--primary)]"
                    : "border-[var(--border)]/35 text-[var(--muted-foreground)]/50 hover:border-[var(--border)]/55 hover:text-[var(--foreground)]"
                }`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragOver(false);
                  const f = e.dataTransfer.files[0];
                  if (f?.type === "application/pdf") {
                    onUploadPdf(f);
                    update("paper_path", "");
                  }
                }}
              >
                <Upload size={11} />
                <span>{t("Upload PDF")}</span>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,application/pdf"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null;
                    if (f) {
                      onUploadPdf(f);
                      update("paper_path", "");
                    }
                    e.target.value = "";
                  }}
                />
              </label>
            )}
          </Field>

          <Field label={t("Parsed Dir")} width="min-w-[120px] flex-1">
            <input
              type="text"
              value={value.paper_path}
              onChange={(e) => {
                onUploadPdf(null);
                update("paper_path", e.target.value);
              }}
              placeholder={t("e.g. 2211asm1")}
              className={`${INPUT_CLS} w-full`}
            />
          </Field>

          <Field label={t("Max")} width="w-[60px]">
            <input
              type="number"
              min={1}
              max={100}
              value={value.max_questions}
              onChange={(e) =>
                update(
                  "max_questions",
                  Math.max(1, Number(e.target.value) || 1),
                )
              }
              className={`${INPUT_CLS} w-full`}
            />
          </Field>
        </div>
      )}
    </>
  );

  if (collapsed === undefined) {
    return <div className="space-y-2.5 px-3.5 py-2.5">{body}</div>;
  }

  return (
    <CollapsibleConfigSection
      collapsed={collapsed}
      summary={summarizeQuizConfig(value, t)}
      onToggleCollapsed={onToggleCollapsed ?? (() => undefined)}
      bodyClassName="px-3.5 pb-2.5 space-y-2.5"
    >
      {body}
    </CollapsibleConfigSection>
  );
});

// ---------------------------------------------------------------------------
// Type multi-select dropdown
// ---------------------------------------------------------------------------

interface TypeMultiSelectProps {
  value: NormalizedQuizQuestionType[];
  onChange: (next: NormalizedQuizQuestionType[]) => void;
}

function TypeMultiSelect({ value, onChange }: TypeMultiSelectProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  // Position of the portal-rendered menu. Computed from the trigger's
  // bounding rect — the menu is rendered into document.body via portal
  // so the parent card's ``overflow-hidden`` doesn't clip it.
  // Position of the portal-rendered menu. We anchor the menu to the
  // trigger's **right** edge (so a wider menu grows leftward into the
  // panel rather than off the viewport) and flip the vertical anchor
  // up vs. down based on remaining space.
  const [menuPos, setMenuPos] = useState<{
    rightCss: number;
    triggerWidth: number;
    triggerRightX: number;
    direction: "down" | "up";
    anchorOffset: number;
  } | null>(null);

  const recomputePosition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const viewportH = window.innerHeight;
    const viewportW = window.innerWidth;
    const menuMaxH = 260;
    const spacing = 4;
    const spaceBelow = viewportH - rect.bottom - spacing;
    const spaceAbove = rect.top - spacing;
    // Flip up only when there's clearly not enough room below AND there
    // is more room above. Otherwise stay anchored down.
    const direction: "down" | "up" =
      spaceBelow >= menuMaxH || spaceBelow >= spaceAbove ? "down" : "up";
    setMenuPos({
      rightCss: Math.max(0, viewportW - rect.right),
      triggerWidth: rect.width,
      triggerRightX: rect.right,
      direction,
      anchorOffset:
        direction === "down"
          ? rect.bottom + spacing
          : viewportH - rect.top + spacing,
    });
  }, []);

  const closeMenu = useCallback(() => {
    setOpen(false);
    setMenuPos(null);
  }, []);

  const toggleMenu = useCallback(() => {
    if (open) {
      closeMenu();
      return;
    }
    setOpen(true);
  }, [closeMenu, open]);

  // Open/close: when the menu is open, listen for outside clicks
  // (mousedown on something outside both the trigger and the menu) and
  // for viewport changes that would move the trigger relative to the
  // page, so the portal-rendered menu follows.
  useLayoutEffect(() => {
    if (open) recomputePosition();
  }, [open, recomputePosition]);

  useEffect(() => {
    if (!open) return;
    function onPointer(e: MouseEvent) {
      const target = e.target as Node | null;
      if (!target) return;
      if (
        triggerRef.current?.contains(target) ||
        menuRef.current?.contains(target)
      ) {
        return;
      }
      closeMenu();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") closeMenu();
    }
    function onReflow() {
      recomputePosition();
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onReflow, true);
    window.addEventListener("resize", onReflow);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onReflow, true);
      window.removeEventListener("resize", onReflow);
    };
  }, [closeMenu, open, recomputePosition]);

  const summary = useMemo(() => {
    if (value.length === 0) return t("Auto");
    if (value.length === 1) return t(QUIZ_TYPE_LABEL_KEYS[value[0]]);
    return `${value.length} ${t("types")}`;
  }, [value, t]);

  // Full list of selected types — surfaced as a native title tooltip on
  // the trigger so the user can see exactly which types are picked when
  // the summary collapses to "N types" (or even just truncates a single
  // long label).
  const triggerTooltip = useMemo(() => {
    if (value.length === 0) return t("Auto");
    return value.map((qt) => t(QUIZ_TYPE_LABEL_KEYS[qt])).join(", ");
  }, [value, t]);

  const toggle = (qt: NormalizedQuizQuestionType | null) => {
    // null = the "Auto" entry — clears the selection.
    if (qt === null) {
      if (value.length === 0) return;
      onChange([]);
      return;
    }
    const has = value.includes(qt);
    onChange(has ? value.filter((x) => x !== qt) : [...value, qt]);
  };

  const menu =
    open && menuPos && typeof document !== "undefined"
      ? createPortal(
          <div
            ref={menuRef}
            style={{
              position: "fixed",
              top:
                menuPos.direction === "down" ? menuPos.anchorOffset : undefined,
              bottom:
                menuPos.direction === "up" ? menuPos.anchorOffset : undefined,
              // Anchor to the trigger's right edge — the menu grows
              // leftward into the panel so long English labels never
              // push it off the viewport.
              right: menuPos.rightCss,
              // Let the menu grow past the (narrow) trigger button so
              // long English labels like "Fill in the Blank" don't get
              // ellipsized. The leftward growth is capped to whatever
              // viewport space exists to the left of the trigger's
              // right edge (minus a small breathing margin).
              minWidth: menuPos.triggerWidth,
              maxWidth: Math.min(
                240,
                Math.max(menuPos.triggerWidth, menuPos.triggerRightX - 8),
              ),
              maxHeight: 260,
              zIndex: 1000,
            }}
            className="overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--card)] py-1 shadow-lg"
          >
            <DropdownRow
              label={t("Auto")}
              active={value.length === 0}
              onClick={() => toggle(null)}
            />
            <div className="my-1 h-px bg-[var(--border)]/40" />
            {QUIZ_QUESTION_TYPES.map((qt) => (
              <DropdownRow
                key={qt}
                label={t(QUIZ_TYPE_LABEL_KEYS[qt])}
                active={value.includes(qt)}
                dotClass={TYPE_ACCENT[qt].dot}
                onClick={() => toggle(qt)}
              />
            ))}
          </div>,
          document.body,
        )
      : null;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        title={triggerTooltip}
        onClick={toggleMenu}
        className={`${INPUT_CLS} flex w-full items-center justify-between gap-1`}
      >
        <span className="min-w-0 truncate text-left">{summary}</span>
        <ChevronDown
          size={12}
          className={`shrink-0 text-[var(--muted-foreground)]/60 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>
      {menu}
    </>
  );
}

function DropdownRow({
  label,
  active,
  dotClass,
  onClick,
}: {
  label: string;
  active: boolean;
  dotClass?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[12px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
    >
      <span
        className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border ${
          active
            ? "border-[var(--primary)] bg-[var(--primary)] text-white"
            : "border-[var(--border)] bg-transparent"
        }`}
      >
        {active ? <Check size={9} strokeWidth={3} /> : null}
      </span>
      {dotClass ? (
        <span className={`h-2 w-2 shrink-0 rounded-full ${dotClass}`} />
      ) : null}
      <span className="min-w-0 flex-1 truncate">{label}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Draggable ratio bar
// ---------------------------------------------------------------------------

interface DraggableRatioBarProps {
  types: NormalizedQuizQuestionType[];
  counts: Partial<Record<NormalizedQuizQuestionType, number>>;
  total: number;
  onChange: (next: Partial<Record<NormalizedQuizQuestionType, number>>) => void;
}

function DraggableRatioBar({
  types,
  counts,
  total,
  onChange,
}: DraggableRatioBarProps) {
  const barRef = useRef<HTMLDivElement>(null);
  // Snapshot of the drag start: which boundary, the pointer x at start,
  // and the counts at start. We compute deltas off the snapshot rather
  // than the live counts so a drag is one atomic gesture.
  const dragRef = useRef<{
    boundaryIdx: number;
    startX: number;
    startCounts: Record<NormalizedQuizQuestionType, number>;
  } | null>(null);

  const safeTotal = Math.max(total, types.length);

  // Cumulative percentage at the right edge of each segment, used to
  // position the drag handles and segment widths.
  const widthsPct = useMemo(
    () => types.map((qt) => ((counts[qt] ?? 0) / safeTotal) * 100),
    [types, counts, safeTotal],
  );
  const cumulativePct = useMemo(() => {
    const out: number[] = [];
    let running = 0;
    for (const w of widthsPct) {
      running += w;
      out.push(running);
    }
    return out;
  }, [widthsPct]);

  const handleBoundaryPointerDown = useCallback(
    (boundaryIdx: number) => (e: React.PointerEvent) => {
      if (!barRef.current) return;
      e.preventDefault();
      e.stopPropagation();
      (e.currentTarget as Element).setPointerCapture(e.pointerId);
      const snapshot: Record<NormalizedQuizQuestionType, number> = {} as Record<
        NormalizedQuizQuestionType,
        number
      >;
      for (const qt of types) {
        snapshot[qt] = counts[qt] ?? 0;
      }
      dragRef.current = {
        boundaryIdx,
        startX: e.clientX,
        startCounts: snapshot,
      };
    },
    [counts, types],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      const drag = dragRef.current;
      if (!drag || !barRef.current) return;
      const rect = barRef.current.getBoundingClientRect();
      if (rect.width <= 0) return;
      const pxPerUnit = rect.width / safeTotal;
      const rawDelta = e.clientX - drag.startX;
      let deltaUnits = Math.round(rawDelta / pxPerUnit);
      if (deltaUnits === 0) return;

      const leftType = types[drag.boundaryIdx];
      const rightType = types[drag.boundaryIdx + 1];
      const leftStart = drag.startCounts[leftType] ?? 1;
      const rightStart = drag.startCounts[rightType] ?? 1;

      // Clamp so neither side drops below 1.
      if (leftStart + deltaUnits < 1) deltaUnits = 1 - leftStart;
      if (rightStart - deltaUnits < 1) deltaUnits = rightStart - 1;
      if (deltaUnits === 0) return;

      const next: Record<string, number> = { ...drag.startCounts };
      next[leftType] = leftStart + deltaUnits;
      next[rightType] = rightStart - deltaUnits;
      onChange(next as Partial<Record<NormalizedQuizQuestionType, number>>);
    },
    [onChange, safeTotal, types],
  );

  const handlePointerUp = useCallback((e: React.PointerEvent) => {
    dragRef.current = null;
    try {
      (e.currentTarget as Element).releasePointerCapture(e.pointerId);
    } catch {
      /* pointer may already be released */
    }
  }, []);

  return (
    <div
      ref={barRef}
      className="relative flex h-9 w-full select-none overflow-hidden rounded-md bg-[var(--muted)]/30"
    >
      {types.map((qt) => {
        const count = counts[qt] ?? 0;
        const widthPct = (count / safeTotal) * 100;
        // Hide the inline count label once the segment is too narrow to
        // fit it cleanly — the legend below the bar still has it.
        const showCount = widthPct >= 12;
        return (
          <div
            key={qt}
            style={{ width: `${widthPct}%` }}
            className={`flex h-full items-center justify-center ${TYPE_ACCENT[qt].fill} text-[12px] font-semibold text-white tabular-nums transition-[width] duration-150`}
          >
            {showCount ? count : null}
          </div>
        );
      })}
      {/* Drag handles for each interior boundary. Wider hit area than
          the visible line so the cursor doesn't fall off easily. */}
      {types.slice(0, -1).map((qt, i) => {
        const leftPct = cumulativePct[i];
        return (
          <div
            key={`boundary-${qt}`}
            role="separator"
            aria-orientation="vertical"
            aria-label="Drag to adjust ratio"
            style={{ left: `${leftPct}%` }}
            onPointerDown={handleBoundaryPointerDown(i)}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
            className="absolute top-0 z-10 flex h-full w-3 -translate-x-1/2 cursor-ew-resize items-center justify-center"
          >
            <span className="h-4 w-[3px] rounded-full bg-white/85 shadow-[0_0_0_1px_rgba(0,0,0,0.08)]" />
          </div>
        );
      })}
    </div>
  );
}
