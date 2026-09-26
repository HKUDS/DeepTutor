import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import path from "node:path";

// The task list has two owners in two languages: the backend decides which
// calls exist (`TaskKind`), the settings page decides how to say them. Nothing
// compares the two — a kind added without wording renders as
// "reading_future_task" in the middle of a Chinese page, and wording left
// behind after a kind is deleted is a row nobody can reach. This is that
// comparison, and the reason the page can name tasks at all instead of
// printing identifiers.

function findWebRoot(): string {
  let dir = __dirname;
  for (let i = 0; i < 8; i++) {
    if (fs.existsSync(path.join(dir, "package.json")) && fs.existsSync(path.join(dir, "locales", "en", "app.json"))) return dir;
    dir = path.dirname(dir);
  }
  throw new Error("could not locate the web root from " + __dirname);
}

const WEB = findWebRoot();
const PAGE = path.join(WEB, "components/settings/TaskModelsWorkspace.tsx");
const TASKS_PY = path.join(
  WEB,
  "..",
  "deeptutor/services/model_selection/tasks.py",
);

function locale(name: string): Record<string, string> {
  return JSON.parse(
    fs.readFileSync(path.join(WEB, "locales", name, "app.json"), "utf8"),
  ) as Record<string, string>;
}

/** The text between a declaration's opening line and the line that closes it. */
function block(source: string, opening: string, closing: string): string {
  const start = source.indexOf(opening);
  assert.notEqual(start, -1, `declaration not found: ${opening}`);
  const rest = source.slice(start + opening.length);
  const end = rest.indexOf(closing);
  assert.notEqual(end, -1, `declaration never closed: ${opening}`);
  return rest.slice(0, end);
}

/** The kinds the backend enumerates, with the group each is listed under. */
function backendKinds(): { id: string; group: string }[] {
  const source = fs.readFileSync(TASKS_PY, "utf8");
  const values = new Map(
    [
      ...block(source, "class TaskKind(StrEnum):", "\n\n\n").matchAll(
        /^ {4}([A-Z_]+) = "([a-z_]+)"$/gm,
      ),
    ].map((match) => [match[1], match[2]]),
  );
  return [
    ...block(
      source,
      "TASK_KINDS: tuple[TaskKindSpec, ...] = (",
      "\n)",
    ).matchAll(/TaskKindSpec\(TaskKind\.([A-Z_]+), "([a-z_]+)"\)/g),
  ].map((match) => {
    const id = values.get(match[1]);
    assert.ok(id, `TaskKind.${match[1]} is listed but not declared`);
    return { id, group: match[2] };
  });
}

function pageTaskText(): Map<string, { label: string; detail: string }> {
  const source = fs.readFileSync(PAGE, "utf8");
  const declared = block(
    source,
    "const TASK_TEXT: Record<string, { label: string; detail: string }> = {",
    "\n};",
  );
  return new Map(
    [
      ...declared.matchAll(
        /(\w+): \{\s*label: "([^"]+)",\s*detail: "([^"]+)",\s*\}/g,
      ),
    ].map((match) => [match[1], { label: match[2], detail: match[3] }]),
  );
}

function pageGroupText(): Map<string, string> {
  const declared = block(
    fs.readFileSync(PAGE, "utf8"),
    "const GROUP_TEXT: Record<string, string> = {",
    "\n};",
  );
  return new Map(
    [...declared.matchAll(/(\w+): "([^"]+)",/g)].map((match) => [
      match[1],
      match[2],
    ]),
  );
}

test("every task the backend runs is named on the page, and nothing else is", () => {
  const kinds = backendKinds();
  const text = pageTaskText();
  const groups = pageGroupText();

  assert.ok(kinds.length >= 10, `expected the backend's list, found ${kinds.length}`);
  const unnamed = kinds.filter((kind) => !text.has(kind.id)).map((k) => k.id);
  assert.deepEqual(unnamed, [], `tasks with no wording: ${unnamed.join(", ")}`);

  const declared = new Set(kinds.map((kind) => kind.id));
  const stale = [...text.keys()].filter((id) => !declared.has(id));
  assert.deepEqual(stale, [], `wording for tasks nobody runs: ${stale.join(", ")}`);

  const ungrouped = [...new Set(kinds.map((kind) => kind.group))].filter(
    (group) => !groups.has(group),
  );
  assert.deepEqual(ungrouped, [], `groups with no heading: ${ungrouped.join(", ")}`);
});

test("every task name and sentence exists in both locales", () => {
  const en = locale("en");
  const zh = locale("zh");
  const strings = [
    ...[...pageTaskText().values()].flatMap((entry) => [
      entry.label,
      entry.detail,
    ]),
    ...pageGroupText().values(),
  ];

  assert.ok(strings.length >= 23, `expected the page's copy, found ${strings.length}`);
  const missing = strings.filter((s) => !(s in en) || !(s in zh));
  assert.deepEqual(missing, [], `copy missing a locale entry: ${missing.join(" | ")}`);
  // An entry that was added to zh untranslated is the same failure as a missing
  // one: the reader still gets English, only with nothing left to grep for.
  const untranslated = strings.filter((s) => zh[s] === s);
  assert.deepEqual(
    untranslated,
    [],
    `copy still in English under zh: ${untranslated.join(" | ")}`,
  );
});
