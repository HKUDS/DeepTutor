import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";

const webRoot = process.cwd();

function readJson(relativePath: string): Record<string, unknown> {
  return JSON.parse(
    readFileSync(path.resolve(webRoot, relativePath), "utf8"),
  ) as Record<string, unknown>;
}

test("ESLint ignores generated and scratch output", () => {
  const config = readFileSync(
    path.resolve(webRoot, "eslint.config.mjs"),
    "utf8",
  );

  for (const ignored of [
    "tmp/**",
    "coverage/**",
    "playwright-report/**",
    "test-results/**",
    "contracts/generated/.tmp/**",
  ]) {
    assert.match(config, new RegExp(`["]${ignored.replaceAll("*", "\\*")}["]`));
  }
});

test("TypeScript includes canonical source roots and no named build output", () => {
  const tsconfig = readJson("tsconfig.json");
  const include = tsconfig.include as string[];

  for (const root of [
    "app",
    "components",
    "context",
    "features",
    "hooks",
    "i18n",
    "lib",
    "shared",
    "contracts",
    "scripts",
    "tests",
  ]) {
    assert.ok(
      include.some((entry) => entry.startsWith(`${root}/`)),
      `missing explicit ${root} include`,
    );
  }

  assert.equal(include.includes("**/*.ts"), false);
  assert.equal(include.includes("**/*.tsx"), false);
  assert.equal(
    include.some((entry) => /^\.next-[^/]+\//.test(entry)),
    false,
    "named one-off Next.js build directories must not enter typecheck",
  );
  assert.ok(include.includes(".next/types/**/*.ts"));
});

test("Next's checked-in environment declaration uses the canonical dev cache", () => {
  const nextEnv = readFileSync(path.resolve(webRoot, "next-env.d.ts"), "utf8");

  assert.match(nextEnv, /import "\.\/\.next\/dev\/types\/routes\.d\.ts";/);
  assert.doesNotMatch(nextEnv, /\.next-[^/]+\//);
});

test("package exposes deterministic frontend checks", () => {
  const packageJson = readJson("package.json");
  const scripts = packageJson.scripts as Record<string, string>;

  assert.equal(scripts.typecheck, "node ./scripts/typecheck.mjs");
  assert.equal(
    scripts["check:fast"],
    "npm run contracts:check && npm run architecture:check && npm run typecheck && npm run test:node && npm run test:unit && npm run lint && npm run i18n:check",
  );
  assert.equal(
    scripts.check,
    "npm run check:fast && npm run build && npm run perf:check",
  );
  assert.match(scripts["test:e2e:critical"], /critical-turns/);
  assert.match(scripts["test:e2e:multi-worker"], /multi-worker-turns-desktop/);
});

test("standalone typecheck ignores stale generated Next route validators", () => {
  const source = readFileSync(
    path.resolve(webRoot, "scripts", "typecheck.mjs"),
    "utf8",
  );

  assert.match(source, /removeNextTypeIncludes\(original\)/);
  assert.match(
    source,
    /tsconfig\.deeptutor-typecheck-\$\{process\.pid\}\.json/,
  );
  assert.match(source, /"-p",\s*isolatedTsconfigPath/);
  assert.match(source, /finally\s*{\s*rmSync\(isolatedTsconfigPath/);
  assert.doesNotMatch(source, /writeFileSync\(tsconfigPath/);
});

test("tracked frontend files contain no generated or backup artifacts", () => {
  const result = spawnSync("git", ["ls-files", "--", "web"], {
    cwd: path.resolve(webRoot, ".."),
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);

  const forbidden = result.stdout
    .split("\n")
    .filter(Boolean)
    .filter((file) =>
      /(?:\.orig$|\.DS_Store$|(?:^|\/)\.next[^/]*(?:\/|$)|(?:^|\/)tmp\/|\.tsbuildinfo$)/.test(
        file,
      ),
    );

  assert.deepEqual(forbidden, []);
});
