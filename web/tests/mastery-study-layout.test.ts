import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

function source(file: string): string {
  return readFileSync(path.resolve(process.cwd(), file), "utf8");
}

/**
 * AssistantResponse is shared by every chat surface and reads both viewer
 * contexts even when a mastery turn has no reading or watching attachment.
 * Missing either provider makes an existing assistant message throw during
 * render, before the bare `/sessions` route can initialise its new session.
 */
test("the mastery study route provides every shared chat viewer context", () => {
  const layout = source("app/(utility)/mastery/[pathId]/sessions/layout.tsx");
  const response = source("components/common/AssistantResponse.tsx");

  assert.match(response, /useReading\(\)/);
  assert.match(response, /useWatching\(\)/);
  assert.match(layout, /import \{ ReadingProvider \}/);
  assert.match(layout, /import \{ WatchingProvider \}/);
  assert.match(layout, /<ReadingProvider>/);
  assert.match(layout, /<WatchingProvider>/);
  assert.match(layout, /<ChatRuntimeProvider>/);
});

test("mastery study exposes the shared transcript navigation and save actions", () => {
  const study = source("components/space/learning/MasteryStudy.tsx");

  assert.match(study, /<TurnNavigator/);
  assert.match(study, /data-chat-column="true"/);
  assert.match(study, /<SaveToNotebookModal/);
  assert.match(study, /aria-label=\{t\("Save to Notebook"\)\}/);
  assert.match(study, /source: "mastery_path"/);
});
