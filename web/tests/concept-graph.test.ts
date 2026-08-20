import assert from "node:assert/strict";
import test from "node:test";

import { renderConceptGraphMermaid } from "../lib/concept-graph";

test("stored concept graphs render complete chapter titles", () => {
  const title =
    "Understanding transformations through complete geometric intuition";
  const rendered = renderConceptGraphMermaid({
    nodes: [
      {
        id: "root",
        label: 'A "quoted" book',
        chapter_id: "",
        description: "",
        weight: 1,
      },
      {
        id: "chapter-one",
        label: title,
        chapter_id: "chapter-1",
        description: "",
        weight: 1,
      },
    ],
    edges: [
      {
        src: "root",
        dst: "chapter-one",
        relation: "depends_on",
        rationale: "",
      },
    ],
  });

  assert.match(rendered, /root\(\["A 'quoted' book"\]\)/);
  assert.ok(rendered.includes(`chapter_one["01 · ${title}"]`));
  assert.ok(rendered.includes("root --> chapter_one"));
  assert.equal(rendered.includes("…"), false);
});
