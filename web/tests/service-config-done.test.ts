import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const read = (relative: string) =>
  readFileSync(path.resolve(process.cwd(), relative), "utf8");

test("provider edits stay in the shared draft until explicitly applied", () => {
  const editor = read("components/settings/ServiceConfigEditor.tsx");
  assert.doesNotMatch(
    editor,
    /finishProviderEditing|<Modal|await applyService/,
  );
  assert.match(editor, /aria-label=\{t\("Provider configuration"\)\}/);
  assert.match(editor, /getActiveProfile\(catalog, service\)/);
  assert.match(editor, /mutateCatalog/);
});
