import assert from "node:assert/strict";
import test from "node:test";

import { viewedKnowledgePoint } from "../components/space/learning/viewed-point";

const modules = [
  {
    knowledge_points: [
      { id: "kp0", name: "First" },
      { id: "kp1", name: "Second" },
    ],
  },
];
const nextPoint = { id: "kp1", name: "Second" };

test("an opening session does not borrow the path's next step", () => {
  assert.equal(viewedKnowledgePoint(modules, null, "study", nextPoint), null);
});

test("a navigation hint places the outline on the point that was opened", () => {
  assert.deepEqual(viewedKnowledgePoint(modules, "kp0", "study", nextPoint), {
    id: "kp0",
    name: "First",
  });
});

test("a loaded study session with no placement still follows next", () => {
  assert.deepEqual(viewedKnowledgePoint(modules, "", "study", nextPoint), nextPoint);
});

test("an outline session is not standing on a knowledge point", () => {
  assert.equal(viewedKnowledgePoint(modules, "", "outline", nextPoint), null);
});
