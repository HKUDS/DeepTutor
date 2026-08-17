import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { safeParseEvent } from "../lib/translation-tasks-api";

test("translation stream parsing flags malformed and unknown events", () => {
  assert.deepEqual(safeParseEvent("{broken", "run-1"), {
    type: "task_updated",
    run_id: "run-1",
    sequence: 0,
    parse_error: true,
  });

  assert.equal(
    safeParseEvent(JSON.stringify({ type: "future_event" }), "run-1")
      .parse_error,
    true,
  );
  assert.deepEqual(safeParseEvent(JSON.stringify({ type: "run_cancelled" }), "run-1"), {
    type: "run_cancelled",
  });

  assert.deepEqual(safeParseEvent(JSON.stringify({ type: "heartbeat" }), "run-1"), {
    type: "heartbeat",
  });
});

test("task board cancels streams when scope changes and only refreshes after the run", () => {
  const source = readFileSync(
    `${process.cwd()}/components/translation/TranslationTaskBoard.tsx`,
    "utf8",
  );

  assert.match(
    source,
    /useEffect\(\(\) => \{\s*closeStream\(\);\s*\}, \[chapterId, closeStream, sourceId, sourceType\]\)/,
  );
  assert.match(source, /const controller = new AbortController\(\)/);
  assert.match(source, /if \(event\.parse_error\)/);
  assert.match(
    source,
    /await translationTaskApi\.streamRun\([\s\S]*const latest = await translationTaskApi\.list/,
  );
});
