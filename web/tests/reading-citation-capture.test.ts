import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

function source(file: string): string {
  return fs.readFileSync(path.resolve(process.cwd(), file), "utf8");
}

test("citation capture extends the existing annotation contract", () => {
  assert.match(
    source("lib/reading-api.ts"),
    /AnnotationKind = [^;]*"citation"/,
  );
  assert.match(
    source("components/reading/ReaderPane.tsx"),
    /commitSelection\("citation", color\)/,
  );
  assert.match(
    source("components/reading/AnnotationPopover.tsx"),
    /label=\{t\(["']Save citation["']\)\}/,
  );
});

test("citations have a dedicated view in the existing annotation sidebar", () => {
  // The view split and the kind predicate moved to the list's pure data
  // module when the component was split up; the tab label stayed in the
  // component. Assert each where it now lives.
  const list = source("components/reading/AnnotationList.tsx");
  const model = source("lib/reading-mark-list.ts");
  assert.match(model, /view === "citations"/);
  assert.match(model, /annotation\.kind === "citation"/);
  assert.match(list, /label=\{t\("Citations"\)\}/);
});
