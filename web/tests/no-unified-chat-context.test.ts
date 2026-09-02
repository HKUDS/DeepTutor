import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const SOURCE_ROOTS = [
  "app",
  "components",
  "features",
  "hooks",
  "lib",
  "shared",
];

function files(directory: string): string[] {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory()
      ? files(target)
      : /\.(ts|tsx)$/.test(entry.name)
        ? [target]
        : [];
  });
}

test("the retired context path cannot return", () => {
  const offenders = SOURCE_ROOTS.flatMap((root) =>
    files(path.resolve(process.cwd(), root)),
  ).filter((file) =>
    fs.readFileSync(file, "utf8").includes("context/UnifiedChatContext"),
  );
  assert.deepEqual(offenders, []);
  assert.equal(
    fs.existsSync(
      path.resolve(process.cwd(), "context/UnifiedChatContext.tsx"),
    ),
    false,
  );
});
