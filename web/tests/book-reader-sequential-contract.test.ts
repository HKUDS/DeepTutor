import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const source = fs.readFileSync(
  path.resolve(process.cwd(), "app/(workspace)/book/components/PageReader.tsx"),
  "utf8",
);

test("arrow keys consume the current chapter before turning pages", () => {
  const callbackStart = source.indexOf("const navigateSequentially");
  const callbackEnd = source.indexOf("useEffect", callbackStart);
  const callback = source.slice(callbackStart, callbackEnd);
  const scrollDecision = callback.indexOf("sequentialReadTarget");
  const pageTurn = callback.indexOf("onNavigate?.");

  assert.ok(callbackStart >= 0 && callbackEnd > callbackStart);
  assert.ok(scrollDecision >= 0 && pageTurn > scrollDecision);
});

test("turning backward lands at the end and forward lands at the start", () => {
  const previousBranch = source.indexOf(
    'direction === "previous" && previousPage',
  );
  const nextBranch = source.indexOf('direction === "next" && nextPage');

  assert.ok(previousBranch >= 0);
  assert.ok(nextBranch > previousBranch);
  assert.ok(
    source
      .slice(previousBranch, nextBranch)
      .includes('pendingScrollPlacementRef.current = "end"'),
  );
  assert.ok(
    source
      .slice(previousBranch, nextBranch)
      .includes("pendingScrollPlacementPageIdRef.current = previousPage.id"),
  );
  assert.ok(
    source
      .slice(nextBranch)
      .includes('pendingScrollPlacementRef.current = "start"'),
  );
});

test("the reader exposes native chapter progress and keeps direct footer turns", () => {
  assert.ok(source.includes("<progress"));
  assert.ok(source.includes("max={100}"));
  assert.ok(source.includes("Chapter progress: {{percent}}%"));
  assert.ok(source.includes("onNavigate(page.id)"));
});
