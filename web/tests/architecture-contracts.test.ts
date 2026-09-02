import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import test from "node:test";

const root = process.cwd();
const sourceRoots = [
  "app",
  "components",
  "context",
  "features",
  "hooks",
  "lib",
  "shared",
];

function sourceFiles(relativeRoot: string): string[] {
  const start = path.join(root, relativeRoot);
  const result: string[] = [];
  const visit = (directory: string) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(target);
      else if (/\.(?:ts|tsx)$/.test(entry.name)) result.push(target);
    }
  };
  visit(start);
  return result;
}

const allSources = sourceRoots.flatMap(sourceFiles);

test("browser storage methods stay behind the shared boundary", () => {
  const violations = allSources
    .filter((file) => !file.endsWith("components/ThemeScript.tsx"))
    .filter((file) => !file.includes("shared/storage/"))
    .filter((file) =>
      /(?:window\.)?(?:localStorage|sessionStorage)\.(?:getItem|setItem|removeItem)/.test(
        fs.readFileSync(file, "utf8"),
      ),
    )
    .map((file) => path.relative(root, file));
  assert.deepEqual(violations, []);
});

test("raw fetch is limited to the shared API client and media preview", () => {
  const allow = new Set([
    "shared/api/client.ts",
    "components/chat/preview/FilePreviewDrawer.tsx",
  ]);
  const violations = allSources
    .filter((file) => /\bfetch\(/.test(fs.readFileSync(file, "utf8")))
    .map((file) => path.relative(root, file))
    .filter((file) => !allow.has(file));
  assert.deepEqual(violations, []);
});

test("source modules cannot import Next route pages", () => {
  const violations = allSources
    .filter((file) =>
      /from\s+["'][^"']*\/page["']/.test(fs.readFileSync(file, "utf8")),
    )
    .map((file) => path.relative(root, file));
  assert.deepEqual(violations, []);
});

test("tracked source contains no editor backups or generated trash", () => {
  const suspicious = execFileSync("git", ["ls-files", "web"], {
    cwd: path.dirname(root),
    encoding: "utf8",
  })
    .split("\n")
    .filter(Boolean)
    .filter(
      (file) =>
        /(?:~|\.bak|\.orig|\.rej)$/.test(file) || file.endsWith("/.DS_Store"),
    );
  assert.deepEqual(suspicious, []);
});
