import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const read = (relative: string) =>
  readFileSync(path.resolve(process.cwd(), relative), "utf8");

test("provider Done applies only the edited model service before closing", () => {
  const editor = read("components/settings/ServiceConfigEditor.tsx");
  const store = read("features/settings/store/SettingsStore.tsx");

  assert.match(
    editor,
    /const finishProviderEditing = useCallback\(async \(\) =>/,
  );
  assert.match(editor, /serviceChanged && !\(await applyService\(service\)\)/);
  assert.match(editor, /onClick=\{\(\) => void finishProviderEditing\(\)\}/);
  assert.match(editor, /disabled=\{applying\}/);
  assert.match(store, /apiUrl\("\/api\/settings\/apply\/service"\)/);
  assert.match(store, /config: draft\.services\[service\]/);
});
