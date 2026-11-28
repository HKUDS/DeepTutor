/**
 * `coco-bars` fenced-block contract: the tutor model writes numbers and
 * steps, the renderer owns all geometry. Kept dependency-free (no zod) so the
 * fork adds no packages on top of upstream.
 */

export type BlockKind = "extra" | "missing" | "band";

export interface BarsGroup {
  readonly id: string;
  readonly name: string;
  /** People / items in the group; drives bar width. Omit when unknown. */
  readonly count?: number;
  /** Text under the bar, e.g. "99人" or "?人". */
  readonly countLabel?: string;
  /** Bar height (the group's average). */
  readonly value: number;
  /** Overrides the value text, e.g. "?" when the height is only a placeholder. */
  readonly valueLabel?: string;
}

export interface AverageLine {
  readonly value: number;
  readonly label?: string;
  /** Group ids the line spans; all groups when omitted. */
  readonly groups?: readonly string[];
}

export interface BarsBlock {
  readonly group: string;
  readonly from: number;
  readonly to: number;
  /**
   * Defaults by position: inside the bar (above a line) = extra,
   * above the bar top (up to a line) = missing.
   */
  readonly kind?: BlockKind;
  readonly label?: string;
}

export interface BarsMove {
  readonly from: string;
  readonly to: string;
  readonly label?: string;
}

export interface BarsBrace {
  readonly groups: readonly string[];
  readonly label: string;
}

export interface BarsStep {
  readonly say: string;
  readonly lines?: readonly AverageLine[];
  readonly blocks?: readonly BarsBlock[];
  readonly moves?: readonly BarsMove[];
  readonly braces?: readonly BarsBrace[];
  readonly formula?: string;
  readonly focus?: readonly string[];
}

export interface BarsSpec {
  readonly title?: string;
  readonly unit?: string;
  readonly groups: readonly BarsGroup[];
  readonly steps: readonly BarsStep[];
}

export type ParseResult =
  | { readonly ok: true; readonly spec: BarsSpec }
  /** `incomplete`: not (yet) valid JSON — usually the reply is still streaming. */
  | { readonly ok: false; readonly error: string; readonly incomplete: boolean };

export const LIMITS = {
  groups: 6,
  steps: 10,
  itemsPerStep: 8,
  text: 120,
  magnitude: 1e9,
  rawChars: 50_000,
} as const;

class SpecError extends Error {}

type Obj = Record<string, unknown>;

function fail(path: string, message: string): never {
  throw new SpecError(`${path}: ${message}`);
}

function asObject(value: unknown, path: string): Obj {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    fail(path, "应为对象");
  }
  return value as Obj;
}

/**
 * Arrays over `max` are cut rather than rejected (models overshoot limits);
 * `strict` arrays (groups) must fit because steps reference them by id.
 */
function asArray(value: unknown, path: string, max: number, min = 0, strict = false): unknown[] {
  if (value === undefined && min === 0) return [];
  if (!Array.isArray(value)) fail(path, "应为数组");
  if (value.length < min) fail(path, `至少需要 ${min} 项`);
  if (value.length > max && strict) fail(path, `最多 ${max} 项`);
  return value.slice(0, max);
}

/** Non-negative finite number within a sane magnitude (averages, counts). */
function asNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) fail(path, "应为数字");
  if (value < 0) fail(path, "不能为负数");
  if (value > LIMITS.magnitude) fail(path, "数值过大");
  return value;
}

function optNumber(value: unknown, path: string): number | undefined {
  return value === undefined || value === null ? undefined : asNumber(value, path);
}

/** Over-long text is shortened with "…" instead of failing the whole figure. */
function asText(value: unknown, path: string): string {
  if (typeof value !== "string" || !value.trim()) fail(path, "应为非空文字");
  const text = value.trim();
  return text.length > LIMITS.text ? `${text.slice(0, LIMITS.text - 1)}…` : text;
}

function optText(value: unknown, path: string): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value === "string" && !value.trim()) return undefined;
  return asText(value, path);
}

function groupRef(value: unknown, path: string, ids: ReadonlySet<string>): string {
  const id = asText(value, path);
  if (!ids.has(id)) fail(path, `没有 id 为「${id}」的组`);
  return id;
}

function groupRefs(value: unknown, path: string, ids: ReadonlySet<string>): string[] | undefined {
  if (value === undefined) return undefined;
  return asArray(value, path, LIMITS.groups, 1).map((v, i) => groupRef(v, `${path}[${i}]`, ids));
}

function parseGroup(value: unknown, i: number): BarsGroup {
  const path = `groups[${i}]`;
  const o = asObject(value, path);
  const count = optNumber(o.count, `${path}.count`);
  if (count !== undefined && count <= 0) fail(`${path}.count`, "应大于 0");
  return {
    id: asText(o.id, `${path}.id`),
    name: asText(o.name, `${path}.name`),
    count,
    countLabel: optText(o.countLabel, `${path}.countLabel`),
    value: asNumber(o.value, `${path}.value`),
    valueLabel: optText(o.valueLabel, `${path}.valueLabel`),
  };
}

const BLOCK_KINDS: ReadonlySet<string> = new Set(["extra", "missing", "band"]);

function parseBlock(value: unknown, path: string, ids: ReadonlySet<string>): BarsBlock {
  const o = asObject(value, path);
  const from = asNumber(o.from, `${path}.from`);
  const to = asNumber(o.to, `${path}.to`);
  if (from === to) fail(path, "from 和 to 不能相同");
  if (o.kind !== undefined && (typeof o.kind !== "string" || !BLOCK_KINDS.has(o.kind))) {
    fail(`${path}.kind`, "应为 extra、missing 或 band");
  }
  return {
    group: groupRef(o.group, `${path}.group`, ids),
    from,
    to,
    kind: o.kind as BlockKind | undefined,
    label: optText(o.label, `${path}.label`),
  };
}

function parseStep(value: unknown, i: number, ids: ReadonlySet<string>): BarsStep {
  const path = `steps[${i}]`;
  const o = asObject(value, path);
  const n = LIMITS.itemsPerStep;
  return {
    say: asText(o.say, `${path}.say`),
    lines: asArray(o.lines, `${path}.lines`, n).map((v, j) => {
      const p = `${path}.lines[${j}]`;
      const line = asObject(v, p);
      return {
        value: asNumber(line.value, `${p}.value`),
        label: optText(line.label, `${p}.label`),
        groups: groupRefs(line.groups, `${p}.groups`, ids),
      };
    }),
    blocks: asArray(o.blocks, `${path}.blocks`, n).map((v, j) => parseBlock(v, `${path}.blocks[${j}]`, ids)),
    moves: asArray(o.moves, `${path}.moves`, n).map((v, j) => {
      const p = `${path}.moves[${j}]`;
      const move = asObject(v, p);
      return {
        from: groupRef(move.from, `${p}.from`, ids),
        to: groupRef(move.to, `${p}.to`, ids),
        label: optText(move.label, `${p}.label`),
      };
    }),
    braces: asArray(o.braces, `${path}.braces`, n).map((v, j) => {
      const p = `${path}.braces[${j}]`;
      const brace = asObject(v, p);
      return {
        groups: groupRefs(brace.groups, `${p}.groups`, ids) ?? fail(`${p}.groups`, "必填"),
        label: asText(brace.label, `${p}.label`),
      };
    }),
    formula: optText(o.formula, `${path}.formula`),
    focus: groupRefs(o.focus, `${path}.focus`, ids),
  };
}

function buildSpec(data: unknown): BarsSpec {
  const root = asObject(data, "根");
  const groups = asArray(root.groups, "groups", LIMITS.groups, 1, true).map(parseGroup);
  const ids = new Set(groups.map((g) => g.id));
  if (ids.size !== groups.length) fail("groups", "组的 id 不能重复");
  return {
    title: optText(root.title, "title"),
    unit: optText(root.unit, "unit"),
    groups,
    steps: asArray(root.steps, "steps", LIMITS.steps, 1).map((s, i) => parseStep(s, i, ids)),
  };
}

/** Parse and validate the raw fence body. Never throws. */
export function parseBarsSpec(raw: string): ParseResult {
  if (raw.length > LIMITS.rawChars) {
    return { ok: false, error: "数据过大", incomplete: false };
  }
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return { ok: false, error: "数据还不完整", incomplete: true };
  }
  try {
    return { ok: true, spec: buildSpec(data) };
  } catch (error: unknown) {
    if (error instanceof SpecError) return { ok: false, error: error.message, incomplete: false };
    throw error;
  }
}
