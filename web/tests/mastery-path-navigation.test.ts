import test from "node:test";
import assert from "node:assert/strict";

import { newMasteryPathChatUrl } from "../lib/mastery-path-navigation";

test("continuing a mastery path opens a fresh associated chat", () => {
  assert.equal(
    newMasteryPathChatUrl("calculus/path 1"),
    "/home?capability=mastery_path&mastery_path_id=calculus%2Fpath+1",
  );
});
