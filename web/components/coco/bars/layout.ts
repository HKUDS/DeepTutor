/**
 * Pure geometry for a `coco-bars` figure. Everything drawn is derived here so
 * proportions are always right regardless of what the model wrote.
 */
import type { BarsBlock, BarsSpec, BlockKind } from "./spec";

export const VIEW = { width: 720, height: 420 } as const;

const PLOT = { left: 40, right: 700, top: 70, base: 330 } as const;
const GAP = 30;
const MIN_BAR = 56;
const MAX_BAR = 240;
const TRUNCATE_RATIO = 0.35;

export interface BarBox {
  readonly id: string;
  readonly name: string;
  readonly countText: string;
  readonly valueText: string;
  readonly x: number;
  readonly width: number;
  readonly top: number;
  readonly focus: boolean;
}

export interface LineBox {
  readonly x1: number;
  readonly x2: number;
  readonly y: number;
  readonly label: string;
  readonly fresh: boolean;
}

export interface BlockBox {
  readonly group: string;
  readonly kind: BlockKind;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly label?: string;
  readonly fresh: boolean;
}

export interface ArrowBox {
  readonly path: string;
  readonly labelX: number;
  readonly labelY: number;
  readonly label?: string;
  readonly fresh: boolean;
}

export interface BraceBox {
  readonly x1: number;
  readonly x2: number;
  readonly y: number;
  readonly label: string;
  readonly fresh: boolean;
}

export interface FigureLayout {
  readonly bars: readonly BarBox[];
  readonly lines: readonly LineBox[];
  readonly blocks: readonly BlockBox[];
  readonly arrows: readonly ArrowBox[];
  readonly braces: readonly BraceBox[];
  readonly formulas: readonly string[];
  readonly truncated: boolean;
  readonly base: number;
}

export interface ValueScale {
  readonly lo: number;
  readonly hi: number;
  readonly truncated: boolean;
  readonly y: (value: number) => number;
}

function fmt(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)));
}

/** Scale over every value in every step, so the figure never jumps between steps. */
export function valueScale(spec: BarsSpec): ValueScale {
  const values = [
    ...spec.groups.map((g) => g.value),
    ...spec.steps.flatMap((s) => [
      ...(s.lines ?? []).map((l) => l.value),
      ...(s.blocks ?? []).flatMap((b) => [b.from, b.to]),
    ]),
  ];
  const vmin = Math.min(...values);
  const vmax = Math.max(...values);
  const spread = vmax - vmin || Math.abs(vmax) || 1;
  const truncated = vmin > 0 && vmin / vmax > TRUNCATE_RATIO;
  const lo = truncated ? vmin - spread * 0.35 : 0;
  // All-zero data would give hi === lo and NaN coordinates.
  const hi = Math.max(vmax + (vmax - lo) * 0.08, lo + 1);
  const y = (value: number): number =>
    PLOT.base - ((value - lo) / (hi - lo)) * (PLOT.base - PLOT.top);
  return { lo, hi, truncated, y };
}

/** Bar widths proportional to head count ("每人一格宽"), clamped to stay legible. */
export function barWidths(counts: readonly (number | undefined)[]): number[] {
  const known = counts.filter((c): c is number => c !== undefined);
  const fallback = known.length ? known.reduce((a, b) => a + b, 0) / known.length : 1;
  const weights = counts.map((c) => c ?? fallback);
  const total = weights.reduce((a, b) => a + b, 0);
  const available = PLOT.right - PLOT.left - GAP * (counts.length + 1);
  const clamped = weights.map((w) => Math.min(MAX_BAR, Math.max(MIN_BAR, (available * w) / total)));
  const sum = clamped.reduce((a, b) => a + b, 0);
  return sum > available ? clamped.map((w) => (w * available) / sum) : clamped;
}

/**
 * extra   = the part of the bar sticking out above an average line (inside the bar);
 * missing = the empty slot between the bar top and a higher average line.
 */
function blockKind(block: BarsBlock, barValue: number): BlockKind {
  if (block.kind) return block.kind;
  return Math.max(block.from, block.to) <= barValue ? "extra" : "missing";
}

/** Layout of the figure as it looks after `step` (0-based, cumulative). */
export function layoutFigure(spec: BarsSpec, step: number): FigureLayout {
  const last = Math.max(0, Math.min(step, spec.steps.length - 1));
  const visible = spec.steps.slice(0, last + 1);
  const scale = valueScale(spec);
  const widths = barWidths(spec.groups.map((g) => g.count));
  const focus = new Set(spec.steps[last].focus ?? []);
  const unit = spec.unit ?? "";

  let cursor = PLOT.left + GAP;
  const bars: BarBox[] = spec.groups.map((g, i) => {
    const box: BarBox = {
      id: g.id,
      name: g.name,
      countText: g.countLabel ?? (g.count !== undefined ? `${fmt(g.count)}人` : "?人"),
      valueText: g.valueLabel ?? `${fmt(g.value)}${unit}`,
      x: cursor,
      width: widths[i],
      top: scale.y(g.value),
      focus: focus.has(g.id),
    };
    cursor += widths[i] + GAP;
    return box;
  });
  const byId = new Map(bars.map((b) => [b.id, b]));
  const valueOf = new Map(spec.groups.map((g) => [g.id, g.value]));

  const lines: LineBox[] = visible.flatMap((s, si) =>
    (s.lines ?? []).map((l) => {
      const span = (l.groups ?? spec.groups.map((g) => g.id)).map((id) => byId.get(id)!);
      return {
        x1: Math.min(...span.map((b) => b.x)) - 16,
        x2: Math.max(...span.map((b) => b.x + b.width)) + 16,
        y: scale.y(l.value),
        label: l.label ?? `平均 ${fmt(l.value)}${unit}`,
        fresh: si === last,
      };
    }),
  );

  const blocks: BlockBox[] = visible.flatMap((s, si) =>
    (s.blocks ?? []).map((b) => {
      const bar = byId.get(b.group)!;
      const top = scale.y(Math.max(b.from, b.to));
      return {
        group: b.group,
        kind: blockKind(b, valueOf.get(b.group)!),
        x: bar.x,
        y: top,
        width: bar.width,
        height: scale.y(Math.min(b.from, b.to)) - top,
        label: b.label,
        fresh: si === last,
      };
    }),
  );

  const anchor = (id: string): { x: number; y: number } => {
    const block = [...blocks].reverse().find((b) => b.group === id);
    const bar = byId.get(id)!;
    return block
      ? { x: block.x + block.width / 2, y: block.y + block.height / 2 }
      : { x: bar.x + bar.width / 2, y: bar.top };
  };

  const arrows: ArrowBox[] = visible.flatMap((s, si) =>
    (s.moves ?? []).map((m) => {
      const a = anchor(m.from);
      const b = anchor(m.to);
      const lift = Math.min(a.y, b.y) - 46;
      const cx = (a.x + b.x) / 2;
      return {
        path: `M ${a.x} ${a.y} Q ${cx} ${lift} ${b.x} ${b.y}`,
        labelX: cx,
        labelY: lift + 12,
        label: m.label,
        fresh: si === last,
      };
    }),
  );

  const braceList = visible.flatMap((s, si) => (s.braces ?? []).map((b) => ({ b, fresh: si === last })));
  const highest = Math.min(...bars.map((b) => b.top), ...blocks.map((b) => b.y), ...lines.map((l) => l.y));
  const braces: BraceBox[] = braceList.map(({ b, fresh }, i) => {
    const span = b.groups.map((id) => byId.get(id)!);
    return {
      x1: Math.min(...span.map((s) => s.x)),
      x2: Math.max(...span.map((s) => s.x + s.width)),
      y: Math.max(PLOT.top - 40, highest - 30 - i * 30),
      label: b.label,
      fresh,
    };
  });

  return {
    bars,
    lines,
    blocks,
    arrows,
    braces,
    formulas: visible.map((s) => s.formula).filter((f): f is string => Boolean(f)),
    truncated: scale.truncated,
    base: PLOT.base,
  };
}
