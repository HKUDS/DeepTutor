import test from "node:test";
import assert from "node:assert/strict";

import { prepareIframeHtml } from "../lib/iframe-html";

function bridgeSource(): string {
  const prepared = prepareIframeHtml(
    "<!doctype html><html><head></head><body><main>content</main></body></html>",
  );
  const match = prepared.match(/<script data-dt-bridge>([\s\S]*?)<\/script>/);
  assert.ok(match, "prepared iframe HTML should contain the host bridge");
  return match[1];
}

test("iframe bridge measures current body content instead of historical viewport height", () => {
  const source = bridgeSource();

  assert.match(source, /body\.scrollHeight > 0/);
  assert.doesNotMatch(
    source,
    /Math\.max\(document\.documentElement\.scrollHeight/,
  );
});

test("iframe bridge observes layout and tab-content changes with coalescing", () => {
  const source = bridgeSource();

  assert.match(source, /new ResizeObserver\(scheduleHeightReport\)/);
  assert.match(source, /new MutationObserver\(scheduleHeightReport\)/);
  assert.match(source, /characterData: true/);
  assert.match(source, /childList: true/);
  assert.match(source, /subtree: true/);
  assert.match(source, /requestAnimationFrame\(run\)/);
});
