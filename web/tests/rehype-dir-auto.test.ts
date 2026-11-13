import test from "node:test";
import assert from "node:assert/strict";
import { rehypeDirAuto } from "../lib/rehype-dir-auto";

const el = (tagName: string, children: unknown[] = [], properties: Record<string, unknown> = {}) => ({
  type: "element",
  tagName,
  properties,
  children,
});
const text = (value: string) => ({ type: "text", value });

function run(tree: ReturnType<typeof el>) {
  rehypeDirAuto()(tree as never);
  return tree;
}

test("prose blocks read their own direction", () => {
  const tree = run(
    el("div", [
      el("p", [text("مرحبا")]),
      el("h2", [text("Title")]),
      el("ul", [el("li", [text("one")])]),
      el("blockquote", [el("p", [text("quote")])]),
      el("table", [el("tr", [el("td", [text("x")])])]),
    ]),
  );
  const [p, h2, ul, quote, table] = tree.children as ReturnType<typeof el>[];
  assert.equal(p.properties.dir, "auto");
  assert.equal(h2.properties.dir, "auto");
  assert.equal(ul.properties.dir, "auto");
  assert.equal((ul.children[0] as ReturnType<typeof el>).properties.dir, "auto");
  assert.equal(quote.properties.dir, "auto");
  assert.equal((quote.children[0] as ReturnType<typeof el>).properties.dir, "auto");
  // The table keeps its column order; only its cells read their own text.
  assert.equal(table.properties.dir, undefined);
  const td = ((table.children[0] as ReturnType<typeof el>).children[0]) as ReturnType<typeof el>;
  assert.equal(td.properties.dir, "auto");
});

test("code blocks and inline code are explicitly left-to-right", () => {
  const tree = run(
    el("div", [
      el("pre", [el("code", [text("x = 1")])]),
      el("p", [el("code", [text("y")])]),
    ]),
  );
  const [pre, p] = tree.children as ReturnType<typeof el>[];
  assert.equal(pre.properties.dir, "ltr");
  assert.equal((pre.children[0] as ReturnType<typeof el>).properties.dir, "ltr");
  assert.equal((p.children[0] as ReturnType<typeof el>).properties.dir, "ltr");
});

test("a direction set in the reply's own HTML is kept", () => {
  const tree = run(el("div", [el("p", [text("x")], { dir: "ltr" })]));
  assert.equal((tree.children[0] as ReturnType<typeof el>).properties.dir, "ltr");
});


test("math and diagrams are isolated inside explicit RTL quotes", () => {
  const tree = run(el("blockquote", [el("span", [], {className: ["katex"]}), el("svg")], {dir: "rtl"}));
  assert.equal(tree.properties.dir, "rtl");
  for (const child of tree.children as ReturnType<typeof el>[]) assert.equal(child.properties.dir, "ltr");
});
