import test from "node:test";
import assert from "node:assert/strict";

import { focusAllowsLocator, focusProgress } from "@/lib/reading-focus";
import type { FocusState } from "@/lib/reading-api";

const state: FocusState = {
  active: true,
  run_id: "run",
  revision: 2,
  plan_hash: "plan",
  passed_checkpoint_ids: ["one"],
  attempts: [],
  checkpoints: [
    {
      checkpoint_id: "one",
      title: "One",
      start_locator: 1,
      end_locator: 2,
      char_count: 100,
    },
    {
      checkpoint_id: "two",
      title: "Two",
      start_locator: 3,
      end_locator: 4,
      char_count: 100,
    },
  ],
  expected_checkpoint: {
    checkpoint_id: "two",
    title: "Two",
    start_locator: 3,
    end_locator: 4,
    char_count: 100,
  },
  completed: false,
  unlocked_through_locator: 4,
  pass_score: 65,
  updated_at: 0,
};

test("Focus Reading allows the current checkpoint but guides later locators back", () => {
  assert.equal(focusAllowsLocator(state, 4), true);
  assert.equal(focusAllowsLocator(state, 5), false);
  assert.equal(focusAllowsLocator({ ...state, active: false }, 5), true);
});

test("Focus Reading derives display progress only from server-returned state", () => {
  assert.deepEqual(focusProgress(state), { passed: 1, total: 2 });
});
