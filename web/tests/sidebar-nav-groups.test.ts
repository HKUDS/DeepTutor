import test from "node:test";
import assert from "node:assert/strict";

import {
  MULTI_USER_DEFAULT_COLLAPSED_NAV_HREFS,
  PRIMARY_NAV,
  SECONDARY_NAV,
} from "../components/sidebar/nav-entries";

test("selected fixed consoles can fold while Settings stays fixed", () => {
  assert.deepEqual(MULTI_USER_DEFAULT_COLLAPSED_NAV_HREFS, [
    "/memory",
    "/knowledge-bases",
  ]);
  assert.deepEqual(
    PRIMARY_NAV.map((entry) => entry.href),
    [
      "/chat",
      "/partners",
      "/agents",
      "/co-writer",
      "/books",
      "/mastery",
      "/reading",
      "/space",
      "/memory",
      "/knowledge-bases",
    ],
  );
  assert.deepEqual(
    SECONDARY_NAV.map((entry) => entry.href),
    ["/settings"],
  );
});
