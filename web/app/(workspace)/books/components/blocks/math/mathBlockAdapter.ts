/**
 * YuEdu fork: 数学交互 block 适配层（保险层）。
 *
 * 老悦学数学组件的 props 是 `{ point: KnowledgePoint }`，读 `point.tool_config`
 * （JSON 字符串）。DT 的 block 协议是 `{ block: Block }`，生成器产物落在
 * `block.payload`。本文件是唯一知道「payload 字段名 -> 组件入参」映射的地方，
 * 组件本体只吃 {@link MathBlockConfig}，不触碰 DT 内部 API。
 *
 * 设计要点：
 * - 输入用结构化类型 {@link MathBlockInput}（与 DT `Block` 结构兼容但不依赖它），
 *   方便脱离 DT 单测。
 * - 读取顺序：优先 `block.payload`（生成器产物），回退 `block.params`（手填参数），
 *   再回退内置默认值——保证 LLM 没填全也不白屏。
 * - 所有数值/字符串都做安全强制转换，避免脏 payload 崩渲染。
 */

/** 与 DT Block 兼容的最小输入形状（结构化类型，无需导入 DT 类型）。 */
export interface MathBlockInput {
  type: string;
  title?: string;
  params?: Record<string, unknown>;
  payload?: Record<string, unknown>;
}

/** 单个数学公式项。 */
export interface FormulaItem {
  tex: string;
  caption: string;
}

/** JSXGraph 元素描述（LLM 可产出的纯数据，组件据此 board.create）。 */
export interface JsxElement {
  type: string;
  params?: unknown[];
  attrs?: Record<string, unknown>;
}

/** ECharts 结构化系列（避免 LLM 产出含函数的非法 option）。 */
export interface ChartSeries {
  name: string;
  type: "bar" | "line" | "pie";
  data: Array<number | null>;
}

/** 维恩图集合圆。 */
export interface VennSet {
  label: string;
}

/** 8 种数学 block 的统一配置（各字段按 type 取用，未用到的留空）。 */
export interface MathBlockConfig {
  type: string;
  title: string;
  description: string;
  hint: string;
  // desmos / geogebra
  expression: string;
  expressions: string[];
  materialId: string;
  commands: string[];
  // geometry (JSXGraph)
  boundingBox: [number, number, number, number];
  axis: boolean;
  grid: boolean;
  elements: JsxElement[];
  // formula
  formulas: FormulaItem[];
  // venn
  sets: VennSet[];
  center: string;
  caption: string;
  // complex
  re: number;
  im: number;
  // chart
  categories: string[];
  series: ChartSeries[];
}

const DEFAULT_BOUNDING_BOX: [number, number, number, number] = [-5, 5, 5, -5];

function str(value: unknown, fallback = "", max = 600): string {
  if (value === null || value === undefined) return fallback;
  const s = String(value).trim();
  return s.slice(0, max);
}

function num(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    if (Number.isFinite(n)) return n;
  }
  return fallback;
}

function strArray(value: unknown, max = 12): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => str(item))
    .filter((s) => s.length > 0)
    .slice(0, max);
}

/** 把 LLM 产出的 expressions 形态（字符串数组 / 对象数组 / 单字符串）归一成字符串数组。 */
function normalizeExpressions(value: unknown): string[] {
  if (typeof value === "string" && value.trim()) {
    return value
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
      .slice(0, 12);
  }
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item.trim();
      if (item && typeof item === "object") {
        const obj = item as Record<string, unknown>;
        return str(obj.formula ?? obj.latex ?? obj.expression);
      }
      return "";
    })
    .filter((s) => s.length > 0)
    .slice(0, 12);
}

function boundingBox(value: unknown): [number, number, number, number] {
  if (!Array.isArray(value) || value.length < 4) return DEFAULT_BOUNDING_BOX;
  const box = value.slice(0, 4).map((v) => num(v, 0));
  return [box[0], box[1], box[2], box[3]] as [number, number, number, number];
}

function elements(value: unknown): JsxElement[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    .map((item) => ({
      type: str(item.type),
      params: Array.isArray(item.params) ? item.params : undefined,
      attrs:
        item.attrs && typeof item.attrs === "object"
          ? (item.attrs as Record<string, unknown>)
          : undefined,
    }))
    .filter((el) => el.type.length > 0)
    .slice(0, 32);
}

function formulas(value: unknown): FormulaItem[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    .map((item) => ({
      tex: str(item.tex ?? item.latex ?? item.formula, "f(x)=x"),
      caption: str(item.caption ?? item.note ?? item.description),
    }))
    .filter((f) => f.tex.length > 0)
    .slice(0, 12);
}

function vennSets(value: unknown): VennSet[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    .map((item) => ({ label: str(item.label ?? item.name, "?") }))
    .filter((s) => s.label.length > 0)
    .slice(0, 3);
}

function series(value: unknown): ChartSeries[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
    .map((item) => {
      const rawType = str(item.type, "bar");
      const chartType: ChartSeries["type"] =
        rawType === "line" || rawType === "pie" ? rawType : "bar";
      const data = Array.isArray(item.data)
        ? item.data.map((d) => (typeof d === "number" && Number.isFinite(d) ? d : null))
        : [];
      return {
        name: str(item.name, "series"),
        type: chartType,
        data,
      };
    })
    .filter((s) => s.data.length > 0)
    .slice(0, 6);
}

const DEFAULT_FORMULAS: FormulaItem[] = [
  { tex: "f(x) = ax^2 + bx + c", caption: "二次函数一般式。" },
  { tex: "x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}", caption: "求根公式。" },
];

const DEFAULT_VENN_SETS: VennSet[] = [
  { label: "集合 A" },
  { label: "集合 B" },
];

/**
 * 把 DT block 适配成数学组件的纯配置。组件不调用本函数以外的 DT API。
 * 未识别 type 返回空配置（渲染层降级为默认占位）。
 */
export function configFromBlock(block: MathBlockInput): MathBlockConfig {
  const payload = (block.payload ?? {}) as Record<string, unknown>;
  const params = (block.params ?? {}) as Record<string, unknown>;
  // 生成器产物优先，手填 params 兜底
  const source = (key: string): unknown => payload[key] ?? params[key];
  const title = str(source("title") ?? block.title);
  const description = str(source("description"));
  const hint = str(source("hint"));

  const expressions = normalizeExpressions(
    source("expressions") ?? source("expression"),
  );
  const formulaList = formulas(source("formulas"));
  const setList = vennSets(source("sets"));

  return {
    type: block.type,
    title,
    description,
    hint,
    expression: expressions[0] ?? str(source("expression"), "y=x^2"),
    expressions,
    materialId: str(source("materialId") ?? source("material_id")),
    commands: strArray(source("commands")),
    boundingBox: boundingBox(
      source("boundingBox") ?? source("boundingbox"),
    ),
    axis: Boolean(source("axis") ?? true),
    grid: Boolean(source("grid") ?? true),
    elements: elements(source("elements")),
    formulas: formulaList.length > 0 ? formulaList : DEFAULT_FORMULAS,
    sets: setList.length > 0 ? setList : DEFAULT_VENN_SETS,
    center: str(source("center"), "A ∩ B"),
    caption: str(
      source("caption"),
      "两集合的交集为重叠区域；并集为两圆覆盖的全部区域。",
    ),
    re: num(source("re"), 3),
    im: num(source("im"), 2),
    categories: strArray(source("categories")),
    series: series(source("series")),
  };
}

/** 各 type 的内置默认配置（payload 为空时组件用此渲染样例，避免白屏）。 */
export function defaultConfigForType(type: string): MathBlockConfig {
  const base: MathBlockConfig = {
    type,
    title: "",
    description: "",
    hint: "",
    expression: "y=x^2",
    expressions: ["y=x^2"],
    materialId: "",
    commands: [],
    boundingBox: DEFAULT_BOUNDING_BOX,
    axis: true,
    grid: true,
    elements: [],
    formulas: DEFAULT_FORMULAS,
    sets: DEFAULT_VENN_SETS,
    center: "A ∩ B",
    caption: "两集合的交集为重叠区域；并集为两圆覆盖的全部区域。",
    re: 3,
    im: 2,
    categories: [],
    series: [],
  };
  return base;
}
