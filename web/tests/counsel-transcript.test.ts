import test from "node:test";
import assert from "node:assert/strict";

import {
  looksLikeCounselSessionEnded,
  looksLikeCrisisRedirect,
} from "../lib/counsel-transcript";

test("counsel reuses crisis redirect heuristics", () => {
  assert.equal(
    looksLikeCrisisRedirect(
      "I am concerned you may be in danger. This system cannot provide crisis intervention.",
    ),
    true,
  );
});

test("looksLikeCounselSessionEnded detects terminal copy", () => {
  assert.equal(
    looksLikeCounselSessionEnded(
      "This counseling session has ended. Start a new session_id to continue.",
    ),
    true,
  );
  assert.equal(looksLikeCounselSessionEnded("ordinary reply"), false);
});
