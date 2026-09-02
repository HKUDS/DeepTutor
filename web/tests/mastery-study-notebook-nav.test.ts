import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

function source(file: string): string {
  return readFileSync(path.resolve(process.cwd(), file), "utf8");
}

/**
 * Mastery Study used to ship only a progress outline rail and Activity panel,
 * dropping the chat turn navigator and Save-to-Notebook entry that regular
 * chat still exposes (#1182). Guard the wiring so those tools stay available
 * on the study surface.
 */
test("MasteryStudy restores turn navigation and Save to Notebook", () => {
  const study = source("components/space/learning/MasteryStudy.tsx");

  assert.match(study, /import \{ TurnNavigator \}/);
  assert.match(study, /from "@\/lib\/chat-outline"/);
  assert.match(study, /buildChatOutline\(/);
  assert.match(study, /<TurnNavigator/);
  assert.match(study, /data-chat-column="true"/);
  assert.match(study, /SaveToNotebookModal/);
  assert.match(study, /t\("Save to Notebook"\)/);
  assert.match(study, /BookmarkPlus/);
  assert.match(study, /setShowSaveModal\(true\)/);
});
