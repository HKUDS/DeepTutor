import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

const WEB_ROOT = process.cwd();
const PLAYWRIGHT_CLI = resolve(
  WEB_ROOT,
  "node_modules",
  "@playwright",
  "test",
  "cli.js",
);

test("managed Playwright runs remove their temporary home", () => {
  const isolatedTmp = mkdtempSync(join(tmpdir(), "deeptutor-pw-test-"));

  try {
    const playwrightArgs = ["test", "--list", "--project=functional-e2e"];
    const result = spawnSync(
      process.execPath,
      "bun" in process.versions
        ? ["x", "playwright", ...playwrightArgs]
        : [PLAYWRIGHT_CLI, ...playwrightArgs],
      {
        cwd: WEB_ROOT,
        encoding: "utf8",
        env: {
          ...process.env,
          PW_MANAGED_SERVERS: "1",
          TMPDIR: isolatedTmp,
        },
      },
    );

    assert.equal(result.status, 0, result.stderr || result.stdout);
    assert.deepEqual(
      readdirSync(isolatedTmp).filter((name) =>
        name.startsWith("deeptutor-e2e-"),
      ),
      [],
    );
  } finally {
    rmSync(isolatedTmp, { force: true, recursive: true });
  }
});
