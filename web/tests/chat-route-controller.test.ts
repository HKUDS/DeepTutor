import assert from "node:assert/strict";
import test from "node:test";

import {
  routeSessionId,
  shouldRevalidateCachedSession,
} from "../features/chat/controllers/useChatRouteSession";

test("route/session selection and cached revalidation stay deterministic", () => {
  assert.equal(routeSessionId("session-1"), "session-1");
  assert.equal(routeSessionId(" "), null);
  assert.equal(
    shouldRevalidateCachedSession({
      routeSessionId: "session-1",
      selectedSessionId: "session-1",
      hasCachedMessages: true,
      isStreaming: false,
    }),
    true,
  );
  assert.equal(
    shouldRevalidateCachedSession({
      routeSessionId: "session-1",
      selectedSessionId: "session-1",
      hasCachedMessages: true,
      isStreaming: true,
    }),
    false,
  );
});
