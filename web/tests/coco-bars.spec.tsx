import { readFileSync } from "node:fs";
import path from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CocoBarsCard from "@/components/coco/bars/CocoBarsCard";
import { barWidths, layoutFigure, valueScale } from "@/components/coco/bars/layout";
import { parseBarsSpec, type BarsSpec } from "@/components/coco/bars/spec";

// 第11讲 第4集 探索6：全校身高分三段，求总人数。
const EP4 = {
  title: "中间段为什么要 ÷7",
  unit: "厘米",
  groups: [
    { id: "low", name: "矮个段", count: 99, value: 122 },
    { id: "mid", name: "中间段", countLabel: "?人", value: 151, valueLabel: "?" },
    { id: "high", name: "高个段", count: 72, value: 163 },
  ],
  steps: [
    { say: "全校按身高分成三段，中间段人数不知道。", focus: ["mid"] },
    {
      say: "第一种分法：中间段＋高个段，平均155。高个段每人比155多几？",
      lines: [{ value: 155, label: "中＋高 平均155", groups: ["mid", "high"] }],
      braces: [{ groups: ["mid", "high"], label: "超过130的同学" }],
    },
    {
      say: "高个段72人，每人多8，一共多576，要补给中间段。",
      blocks: [{ group: "high", from: 155, to: 163, label: "每人多8" }],
      moves: [{ from: "high", to: "mid", label: "补576" }],
      formula: "72 × 8 ＝ 576",
    },
    {
      say: "第二种分法：矮个段＋中间段，平均148。矮个段每人少26。",
      lines: [{ value: 148, label: "矮＋中 平均148", groups: ["low", "mid"] }],
      blocks: [{ group: "low", from: 122, to: 148, label: "每人少26" }],
      formula: "99 × 26 ＝ 2574",
    },
    {
      say: "中间段每人身上夹着148到155这7厘米，被两条线分成上下两截。",
      blocks: [{ group: "mid", from: 148, to: 155, kind: "band", label: "每人7厘米" }],
      formula: "7 × 人数 ＝ 2574 ＋ 576 ＝ 3150",
      focus: ["mid"],
    },
    { say: "每人7厘米，一共3150厘米，有几个人？", formula: "人数 ＝ 3150 ÷ 7 ＝ 450" },
  ],
};

function parsed(data: unknown = EP4): BarsSpec {
  const result = parseBarsSpec(JSON.stringify(data));
  if (!result.ok) throw new Error(result.error);
  return result.spec;
}

describe("parseBarsSpec", () => {
  it("accepts the episode 4 diagram", () => {
    const spec = parsed();
    expect(spec.groups).toHaveLength(3);
    expect(spec.steps[2].blocks?.[0]).toMatchObject({ group: "high", from: 155, to: 163 });
  });

  it("accepts the example the tutor skill teaches the model", () => {
    const skill = readFileSync(path.resolve(__dirname, "../../coco/skills/coco-bars/SKILL.md"), "utf-8");
    const example = /```coco-bars\n([\s\S]*?)\n```/.exec(skill.split("## 示例")[1] ?? "")?.[1];
    expect(example).toBeTruthy();
    const result = parseBarsSpec(example!);
    expect(result.ok ? "ok" : result.error).toBe("ok");
  });

  it("reports incomplete JSON while a reply is still streaming", () => {
    const result = parseBarsSpec('{"groups": [');
    expect(result.ok).toBe(false);
  });

  it.each([
    [{ ...EP4, groups: [] }, "groups"],
    [{ ...EP4, groups: [EP4.groups[0], EP4.groups[0]] }, "不能重复"],
    [{ ...EP4, steps: [{ say: "x", blocks: [{ group: "nope", from: 1, to: 2 }] }] }, "nope"],
    [{ ...EP4, steps: [{ say: "x", blocks: [{ group: "low", from: 2, to: 2 }] }] }, "不能相同"],
    [{ ...EP4, steps: [{ say: "x", blocks: [{ group: "low", from: 1, to: 2, kind: "boom" }] }] }, "kind"],
    [{ ...EP4, groups: [{ id: "a", name: "甲", value: "高" }] }, "value"],
    [{ ...EP4, steps: [] }, "steps"],
    [{ ...EP4, groups: [{ id: "a", name: "甲", value: -5 }] }, "负数"],
    [{ ...EP4, groups: [{ id: "a", name: "甲", value: 1e300 }] }, "过大"],
    [{ ...EP4, groups: Array.from({ length: 7 }, (_, i) => ({ id: `g${i}`, name: "组", value: 1 })) }, "最多 6"],
  ])("rejects invalid spec %#", (data, message) => {
    const result = parseBarsSpec(JSON.stringify(data));
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toContain(message);
      expect(result.incomplete).toBe(false);
    }
  });

  it("flags streaming-incomplete JSON separately from bad data", () => {
    const result = parseBarsSpec('{"groups": [');
    expect(result).toMatchObject({ ok: false, incomplete: true });
    expect(parseBarsSpec("x".repeat(60_000))).toMatchObject({ ok: false, incomplete: false });
  });

  it("forgives model overshoot: long text is shortened, extra steps are cut, blank labels dropped", () => {
    const spec = parsed({
      ...EP4,
      steps: [
        { say: "很".repeat(200), lines: [{ value: 140, label: "  " }] },
        ...Array.from({ length: 12 }, () => ({ say: "下一步" })),
      ],
    });
    expect(spec.steps).toHaveLength(10);
    expect(spec.steps[0].say).toHaveLength(120);
    expect(spec.steps[0].say.endsWith("…")).toBe(true);
    expect(spec.steps[0].lines?.[0].label).toBeUndefined();
  });
});

describe("layout", () => {
  it("makes bar width proportional to head count", () => {
    const [low, , high] = barWidths([99, undefined, 72]);
    expect(low / high).toBeCloseTo(99 / 72, 1);
  });

  it("keeps tiny groups legible", () => {
    const widths = barWidths([1, 100]);
    expect(Math.min(...widths)).toBeGreaterThanOrEqual(56);
  });

  it("truncates the axis when all values are far from zero", () => {
    const scale = valueScale(parsed());
    expect(scale.truncated).toBe(true);
    expect(scale.y(163)).toBeLessThan(scale.y(155));
    expect(scale.y(155)).toBeLessThan(scale.y(148));
  });

  it("keeps the scale fixed across steps so bars never jump", () => {
    const spec = parsed();
    const geometry = (step: number) => layoutFigure(spec, step).bars.map(({ x, width, top }) => ({ x, width, top }));
    expect(geometry(0)).toEqual(geometry(5));
  });

  it("accumulates steps and marks only the newest items as fresh", () => {
    const layout = layoutFigure(parsed(), 3);
    expect(layout.lines).toHaveLength(2);
    expect(layout.lines.map((l) => l.fresh)).toEqual([false, true]);
    expect(layout.formulas).toEqual(["72 × 8 ＝ 576", "99 × 26 ＝ 2574"]);
  });

  it("infers extra above a bar and missing below a line", () => {
    const kinds = layoutFigure(parsed(), 4).blocks.map((b) => `${b.group}:${b.kind}`);
    expect(kinds).toEqual(["high:extra", "low:missing", "mid:band"]);
  });

  it("draws a 7cm band whose height matches the 148–155 lines", () => {
    const layout = layoutFigure(parsed(), 4);
    const band = layout.blocks.find((b) => b.kind === "band")!;
    const [l155, l148] = layout.lines;
    expect(band.y).toBeCloseTo(l155.y);
    expect(band.y + band.height).toBeCloseTo(l148.y);
  });

  it("never produces NaN coordinates for all-zero data", () => {
    const spec = parsed({ groups: [{ id: "a", name: "甲", value: 0 }], steps: [{ say: "x", lines: [{ value: 0 }] }] });
    const layout = layoutFigure(spec, 0);
    const numbers = [...layout.bars.flatMap((b) => [b.x, b.width, b.top]), ...layout.lines.map((l) => l.y)];
    expect(numbers.every(Number.isFinite)).toBe(true);
  });

  it("clamps out-of-range steps", () => {
    expect(layoutFigure(parsed(), 99).formulas).toHaveLength(4);
    expect(layoutFigure(parsed(), -3).lines).toHaveLength(0);
  });
});

describe("CocoBarsCard", () => {
  it("walks through the steps one at a time", () => {
    render(<CocoBarsCard raw={JSON.stringify(EP4)} />);
    expect(screen.getByText("全校按身高分成三段，中间段人数不知道。")).toBeInTheDocument();
    const prev = screen.getByRole("button", { name: "上一步" });
    expect(prev).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(prev);
    expect(screen.getByText(/第 1\/6 步/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByText(/第一种分法/)).toBeInTheDocument();
    expect(screen.getAllByTestId("average-line")).toHaveLength(1);

    const showAll = screen.getByRole("button", { name: "全部显示" });
    showAll.focus();
    fireEvent.click(showAll);
    expect(screen.getByText("人数 ＝ 3150 ÷ 7 ＝ 450")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一步" })).toHaveAttribute("aria-disabled", "true");
    expect(document.activeElement).toBe(showAll); // focus is not dropped to <body>
    expect(screen.getByTestId("block-mid-band")).toBeInTheDocument();
    expect(screen.getByTestId("axis-break")).toBeInTheDocument();
  });

  it("shows a calm placeholder while the reply is still streaming", () => {
    render(<CocoBarsCard raw='{"groups": [' />);
    expect(screen.getByRole("note")).toHaveTextContent("正在画图");
  });

  it("explains invalid data instead of crashing", () => {
    render(<CocoBarsCard raw={JSON.stringify({ ...EP4, groups: [] })} />);
    expect(screen.getByRole("note")).toHaveTextContent("柱形图暂时画不出来");
    expect(screen.getByText("查看原始数据")).toBeInTheDocument();
  });

  it("starts again at step 1 when the diagram data changes", () => {
    const { rerender } = render(<CocoBarsCard raw={JSON.stringify(EP4)} />);
    fireEvent.click(screen.getByRole("button", { name: "全部显示" }));
    rerender(<CocoBarsCard raw={JSON.stringify({ ...EP4, title: "重新生成" })} />);
    expect(screen.getByText(/第 1\/6 步/)).toBeInTheDocument();
  });

  it("hides navigation for a single-step figure", () => {
    render(<CocoBarsCard raw={JSON.stringify({ ...EP4, steps: [EP4.steps[0]] })} />);
    expect(screen.queryByRole("button", { name: "下一步" })).not.toBeInTheDocument();
  });
});
