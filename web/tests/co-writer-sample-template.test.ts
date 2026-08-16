import assert from "node:assert/strict";
import test from "node:test";

import { CO_WRITER_SAMPLE_TEMPLATE } from "../app/(workspace)/co-writer/sampleTemplate";

test("Co-Writer sample demonstrates current rendering blocks", () => {
  assert.ok(CO_WRITER_SAMPLE_TEMPLATE.length <= 5000);
  assert.match(CO_WRITER_SAMPLE_TEMPLATE, /```mermaid\nflowchart TD\n/);
  assert.match(CO_WRITER_SAMPLE_TEMPLATE, /```mermaid\nsequenceDiagram\n/);
  assert.doesNotMatch(CO_WRITER_SAMPLE_TEMPLATE, /```(?:flow|seq)\n/);

  for (const capability of [
    "chat",
    "deep_solve",
    "deep_question",
    "deep_research",
    "visualize",
    "math_animator",
  ]) {
    assert.ok(CO_WRITER_SAMPLE_TEMPLATE.includes("`" + capability + "`"));
  }
});

test("Co-Writer sample avoids invented settings and unsupported diagrams", () => {
  assert.doesNotMatch(CO_WRITER_SAMPLE_TEMPLATE, /co_writer_template/);
  assert.doesNotMatch(CO_WRITER_SAMPLE_TEMPLATE, /<script|<iframe|javascript:/i);
});
