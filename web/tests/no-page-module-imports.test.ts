import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const roots = ["app", "components", "features", "hooks", "lib", "shared"];

function sourceFiles(root: string): string[] {
  const absolute = path.resolve(process.cwd(), root);
  if (!fs.existsSync(absolute)) return [];
  const files: string[] = [];
  const visit = (directory: string) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(target);
      else if (/\.(?:ts|tsx)$/.test(entry.name)) files.push(target);
    }
  };
  visit(absolute);
  return files;
}

test("frontend modules never import a Next route page", () => {
  const violations: string[] = [];
  for (const file of roots.flatMap(sourceFiles)) {
    const source = fs.readFileSync(file, "utf8");
    if (/from\s+["'][^"']*\/page["']/.test(source)) {
      violations.push(path.relative(process.cwd(), file));
    }
  }
  assert.deepEqual(violations, []);
});

test("the retired Settings Context path cannot return", () => {
  assert.equal(
    fs.existsSync(
      path.resolve(process.cwd(), "components/settings/SettingsContext.tsx"),
    ),
    false,
  );
  const violations = roots
    .flatMap(sourceFiles)
    .filter((file) =>
      fs
        .readFileSync(file, "utf8")
        .includes("components/settings/SettingsContext"),
    )
    .map((file) => path.relative(process.cwd(), file));
  assert.deepEqual(violations, []);
});
