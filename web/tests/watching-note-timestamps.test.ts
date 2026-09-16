import assert from "node:assert/strict";
import test from "node:test";

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const PANE_PATH = resolve(
  process.cwd(),
  "components/watching/WatchingPane.tsx",
);
const source = readFileSync(PANE_PATH, "utf8");

test("note anchor time is captured at first keystroke, not save time", () => {
  assert.match(source, /noteAnchorTime.*useState<number \| null>/);
  assert.match(
    source,
    /if \(!noteDraft\.trim\(\) && next\.trim\(\)\) \{\s*setNoteAnchorTime\(time\)/,
  );
});

test("addNote uses anchor time instead of live playback time", () => {
  assert.match(source, /const anchorTime = noteAnchorTime \?\? time/);
  assert.match(source, /createVideoNote\(requestedMaterialId, noteDraft\.trim\(\), anchorTime\)/);
});

test("draft is cleared and anchor is reset on successful save", () => {
  assert.match(source, /setNoteDraft\(''\)/);
  assert.match(source, /setNoteAnchorTime\(null\)/);
});

test("note submit has a duplicate guard ref", () => {
  assert.match(source, /noteSubmitGuardRef/);
});

test("list load has a stale-request guard ref", () => {
  assert.match(source, /notesLoadRequestRef/);
});

test("delete error is shown inside the confirmation dialog", () => {
  assert.match(source, /deleteError/);
  assert.match(
    source,
    /ConfirmDialog[\s\S]*?deleteError && \([\s\S]*?<p role="alert"/,
  );
});
