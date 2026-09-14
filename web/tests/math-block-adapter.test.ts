import test from "node:test";
import assert from "node:assert/strict";

import {
  configFromBlock,
  defaultConfigForType,
} from "@/app/(workspace)/books/components/blocks/math/mathBlockAdapter";

test("desmos: extracts expressions and joins first as expression", () => {
  const cfg = configFromBlock({
    type: "desmos",
    title: "二次函数",
    payload: {
      title: "二次函数图像",
      description: "观察开口方向",
      expressions: ["y=x^2", "y=2x+1"],
    },
  });
  assert.deepEqual(cfg.expressions, ["y=x^2", "y=2x+1"]);
  assert.equal(cfg.expression, "y=x^2");
  assert.equal(cfg.title, "二次函数图像");
  assert.equal(cfg.description, "观察开口方向");
});

test("desmos: falls back to params then to default expression", () => {
  const fromParams = configFromBlock({
    type: "desmos",
    params: { expression: "y=sin(x)" },
  });
  assert.equal(fromParams.expression, "y=sin(x)");
  assert.deepEqual(fromParams.expressions, ["y=sin(x)"]);

  const empty = configFromBlock({ type: "desmos" });
  assert.equal(empty.expression, "y=x^2");
});

test("formula: parses formulas array with tex/caption", () => {
  const cfg = configFromBlock({
    type: "formula",
    payload: {
      formulas: [
        { tex: "a^2+b^2=c^2", caption: "勾股定理" },
        { latex: "x=1", note: "根" },
      ],
    },
  });
  assert.equal(cfg.formulas.length, 2);
  assert.equal(cfg.formulas[0].tex, "a^2+b^2=c^2");
  assert.equal(cfg.formulas[1].tex, "x=1");
  assert.equal(cfg.formulas[1].caption, "根");
});

test("formula: empty payload yields default formulas", () => {
  const cfg = configFromBlock({ type: "formula" });
  assert.ok(cfg.formulas.length >= 1);
  assert.ok(cfg.formulas[0].tex.length > 0);
});

test("complex: reads re/im as numbers with fallback", () => {
  const cfg = configFromBlock({ type: "complex", payload: { re: 4, im: -2 } });
  assert.equal(cfg.re, 4);
  assert.equal(cfg.im, -2);
  const empty = configFromBlock({ type: "complex" });
  assert.equal(empty.re, 3);
  assert.equal(empty.im, 2);
});

test("venn: extracts sets and falls back to default center", () => {
  const cfg = configFromBlock({
    type: "venn",
    payload: { sets: [{ label: "A" }, { label: "B" }, { label: "C" }] },
  });
  assert.equal(cfg.sets.length, 3);
  assert.equal(cfg.center, "A ∩ B");
  const empty = configFromBlock({ type: "venn" });
  assert.equal(empty.sets.length, 2);
});

test("chart: parses categories and series, drops non-numeric data", () => {
  const cfg = configFromBlock({
    type: "chart",
    payload: {
      categories: ["周一", "周二"],
      series: [{ name: "销量", type: "bar", data: [5, "bad", 8] }],
    },
  });
  assert.deepEqual(cfg.categories, ["周一", "周二"]);
  assert.equal(cfg.series.length, 1);
  assert.deepEqual(cfg.series[0].data, [5, null, 8]);
  assert.equal(cfg.series[0].type, "bar");
});

test("geometry: reads boundingBox and elements", () => {
  const cfg = configFromBlock({
    type: "geometry",
    payload: {
      boundingBox: [-6, 4, 6, -3],
      elements: [{ type: "point", params: [[1, 2]] }],
    },
  });
  assert.deepEqual(cfg.boundingBox, [-6, 4, 6, -3]);
  assert.equal(cfg.elements.length, 1);
  assert.equal(cfg.elements[0].type, "point");
});

test("geometry: missing boundingBox falls back to default", () => {
  const cfg = configFromBlock({ type: "geometry", payload: {} });
  assert.deepEqual(cfg.boundingBox, [-5, 5, 5, -5]);
});

test("geogebra: reads materialId and commands", () => {
  const cfg = configFromBlock({
    type: "geogebra",
    payload: { materialId: "kungfmxk", commands: ["(1,2)", "y=x^2"] },
  });
  assert.equal(cfg.materialId, "kungfmxk");
  assert.deepEqual(cfg.commands, ["(1,2)", "y=x^2"]);
});

test("three_scene: passes through title/hint", () => {
  const cfg = configFromBlock({
    type: "three_scene",
    title: "正方体",
    payload: { title: "正方体的面棱顶点", hint: "拖动旋转" },
  });
  assert.equal(cfg.title, "正方体的面棱顶点");
  assert.equal(cfg.hint, "拖动旋转");
});

test("defaultConfigForType returns sensible defaults per type", () => {
  const d = defaultConfigForType("desmos");
  assert.equal(d.expression, "y=x^2");
  const f = defaultConfigForType("formula");
  assert.ok(f.formulas.length >= 1);
});

test("configFromBlock tolerates malformed payload without throwing", () => {
  const cfg = configFromBlock({
    type: "desmos",
    payload: { expressions: 12345, title: 123 },
  });
  assert.equal(cfg.title, "123");
  assert.deepEqual(cfg.expressions, []);
  assert.equal(cfg.expression, "y=x^2");
});

test("configFromBlock accepts a single expression string split by newlines", () => {
  const cfg = configFromBlock({
    type: "desmos",
    payload: { expression: "y=x\ny=2x" },
  });
  assert.deepEqual(cfg.expressions, ["y=x", "y=2x"]);
  assert.equal(cfg.expression, "y=x");
});
