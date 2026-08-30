import test from "node:test";
import assert from "node:assert/strict";

import type { TopicDraft } from "../lib/learning-api";
import {
  isRouteDraftValid,
  moveRouteModule,
  moveRouteWaypoint,
  routeDraftIssues,
} from "../components/space/learning/route-draft";

function draft(): TopicDraft {
  return {
    description: "A trail",
    modules: [
      {
        id: "m1",
        name: "First",
        order: 0,
        knowledge_points: [
          { id: "kp1", name: "One", type: "concept", module_id: "m1" },
          { id: "kp2", name: "Two", type: "procedure", module_id: "m1" },
        ],
      },
      {
        id: "m2",
        name: "Second",
        order: 1,
        knowledge_points: [
          { id: "kp3", name: "Three", type: "memory", module_id: "m2" },
        ],
      },
    ],
  };
}

test("route reorder carries stable ids while normalizing positional fields", () => {
  const reorderedModules = moveRouteModule(draft(), 1, 0);
  assert.deepEqual(
    reorderedModules.modules.map((module) => [module.id, module.order]),
    [
      ["m2", 0],
      ["m1", 1],
    ],
  );

  const reorderedWaypoints = moveRouteWaypoint(draft(), 0, 1, 0);
  assert.deepEqual(
    reorderedWaypoints.modules[0].knowledge_points.map((point) => point.id),
    ["kp2", "kp1"],
  );
  assert.ok(
    reorderedWaypoints.modules[0].knowledge_points.every(
      (point) => point.module_id === "m1",
    ),
  );
});

test("route validation catches every draft shape the API would reject", () => {
  const invalid = draft();
  invalid.modules[0].name = "  ";
  invalid.modules[0].knowledge_points[0].name = "";
  invalid.modules[1].knowledge_points = [];

  assert.equal(isRouteDraftValid(invalid), false);
  assert.deepEqual(
    routeDraftIssues(invalid).map((issue) => issue.code),
    ["blank_region", "blank_waypoint", "no_waypoints"],
  );
  assert.equal(isRouteDraftValid(draft()), true);
  assert.deepEqual(routeDraftIssues({ description: "", modules: [] }), [
    { code: "no_regions" },
  ]);
});
