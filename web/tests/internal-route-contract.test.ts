import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const ROOT = process.cwd();
const APP_ROOT = path.join(ROOT, "app");
const SOURCE_ROOTS = ["app", "components", "context", "features", "hooks", "lib", "shared"];

function walk(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const absolute = path.join(directory, name);
    return statSync(absolute).isDirectory() ? walk(absolute) : [absolute];
  });
}

function pagePattern(pageFile: string): RegExp {
  const relative = path.relative(APP_ROOT, path.dirname(pageFile));
  const segments = relative
    .split(path.sep)
    .filter((segment) => segment && !/^\(.+\)$/.test(segment) && !segment.startsWith("@"));
  let expression = "";
  for (const segment of segments) {
    if (/^\[\[\.\.\..+\]\]$/.test(segment)) {
      expression += "(?:/.+)?";
    } else if (/^\[\.\.\..+\]$/.test(segment)) {
      expression += "/.+";
    } else if (/^\[.+\]$/.test(segment)) {
      expression += "/[^/]+";
    } else {
      expression += `/${segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`;
    }
  }
  return new RegExp(`^${expression || "/"}/?$`);
}

const pagePatterns = walk(APP_ROOT)
  .filter((file) => /\/page\.(?:ts|tsx|js|jsx)$/.test(file))
  .map(pagePattern);

function isPagePath(value: string): boolean {
  const pathname = value.split(/[?#]/, 1)[0] || "/";
  return pagePatterns.some((pattern) => pattern.test(pathname));
}

function literalNavigationTargets(file: string): string[] {
  const source = readFileSync(file, "utf8");
  const targets: string[] = [];
  const patterns = [
    /\bhref\s*[:=]\s*["'`]([^"'`]+)["'`]/g,
    /\b(?:router\.(?:push|replace)|redirect|permanentRedirect)\(\s*["'`]([^"'`]+)["'`]/g,
  ];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      const target = match[1];
      if (target.startsWith("/") && !target.includes("${")) targets.push(target);
    }
  }
  return targets;
}

test("literal frontend navigation targets resolve to real pages", () => {
  const failures: string[] = [];
  for (const root of SOURCE_ROOTS) {
    for (const file of walk(path.join(ROOT, root))) {
      if (!/\.(?:ts|tsx|js|jsx)$/.test(file) || file.includes(`${path.sep}generated${path.sep}`)) {
        continue;
      }
      for (const target of literalNavigationTargets(file)) {
        if (
          target.startsWith("/api/") ||
          target.startsWith("/ws/") ||
          target.startsWith("/files/") ||
          /\.(?:png|jpe?g|gif|svg|ico|webp|woff2?)(?:[?#]|$)/i.test(target)
        ) {
          continue;
        }
        if (!isPagePath(target)) {
          failures.push(`${path.relative(ROOT, file)} -> ${target}`);
        }
      }
    }
  }
  assert.deepEqual(failures, []);
});

test("session URLs accept zero or one session id, never extra segments", () => {
  for (const [indexPath, sessionPath, invalidPath] of [
    ["/chat", "/chat/session-1", "/chat/session-1/extra"],
    [
      "/mastery/path-1/sessions",
      "/mastery/path-1/sessions/session-1",
      "/mastery/path-1/sessions/session-1/extra",
    ],
    [
      "/reading/workspace-1/sessions",
      "/reading/workspace-1/sessions/session-1",
      "/reading/workspace-1/sessions/session-1/extra",
    ],
  ]) {
    assert.equal(isPagePath(indexPath), true, indexPath);
    assert.equal(isPagePath(sessionPath), true, sessionPath);
    assert.equal(isPagePath(invalidPath), false, invalidPath);
  }
});

test("retired bookmark compatibility routes stay removed", () => {
  assert.equal(
    existsSync(path.join(APP_ROOT, "(workspace)/partners/groups/page.tsx")),
    false,
  );
  const config = readFileSync(path.join(ROOT, "next.config.js"), "utf8");
  assert.doesNotMatch(config, /\/space\/learning/);

});
