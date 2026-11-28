import test from "node:test";
import assert from "node:assert/strict";
import {
  hasMarkdownTable,
  separateMarkdownTables,
} from "../lib/markdown-table";

test("hasMarkdownTable only fires on a real GFM delimiter row", () => {
  assert.equal(
    hasMarkdownTable(["引言", "| a | b |", "|---|---|", "| 1 | 2 |"].join("\n")),
    true,
  );
  assert.equal(hasMarkdownTable("| a | b |\n|:--|--:|\n| 1 | 2 |"), true);
  assert.equal(hasMarkdownTable("单列：\n| --- |\n| 1 |"), true);
  // Prose and inline pipes are not a table.
  assert.equal(hasMarkdownTable("a | b 只是写法"), false);
  assert.equal(hasMarkdownTable("---"), false);
  assert.equal(hasMarkdownTable("价格：$a - b$"), false);
});

test("separateMarkdownTables ends a table before the sentence under it", () => {
  // GFM reads the closing question as one more row when no blank line follows.
  const prompt = [
    "转移矩阵如下：",
    "| 本期\\下期 | 转到状态1 |",
    "|---|---|",
    "| 处于状态1 | 0.9 |",
    "下列说法正确的是？",
  ].join("\n");
  assert.equal(
    separateMarkdownTables(prompt),
    [
      "转移矩阵如下：",
      "| 本期\\下期 | 转到状态1 |",
      "|---|---|",
      "| 处于状态1 | 0.9 |",
      "",
      "下列说法正确的是？",
    ].join("\n"),
  );
  // An already separated table is left alone.
  const separated = "| a |\n|---|\n| 1 |\n\n尾句";
  assert.equal(separateMarkdownTables(separated), separated);
  assert.equal(
    separateMarkdownTables("没有表格 | 只有一句话"),
    "没有表格 | 只有一句话",
  );
});
