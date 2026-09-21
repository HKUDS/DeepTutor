import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { expect, it } from "vitest";

const audit = path.resolve("scripts/i18n_audit.mjs");

function runAudit(source: string, en: Record<string, string>, zh = en) {
  const root = mkdtempSync(path.join(tmpdir(), "deeptutor-i18n-"));
  try {
    for (const [locale, entries] of Object.entries({ en, zh })) {
      mkdirSync(path.join(root, "locales", locale), { recursive: true });
      writeFileSync(path.join(root, "locales", locale, "app.json"), JSON.stringify(entries));
    }
    mkdirSync(path.join(root, "hooks"));
    writeFileSync(path.join(root, "hooks", "sample.ts"), source);
    return spawnSync(process.execPath, [audit, "--show-missing"], { cwd: root, encoding: "utf8" });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

it("fails for keys absent from both locales, including .ts and conditional calls", () => {
  const result = runAudit('t(active ? "Enabled" : "Disabled"); i18n.t("Missing");', { Enabled: "Enabled" });
  expect(result.status).toBe(1);
  expect(result.stdout).toContain('"Disabled"');
  expect(result.stdout).toContain('"Missing"');
});

it("decodes escaped and multiline keys and ignores comments and string contents", () => {
  const source = '// t("Not a call")\nconst example = \'t("Also not a call")\';\nt("Say \\\"hello\\\""); t(`First\nSecond`);';
  const result = runAudit(source, { 'Say "hello"': "Hello", "First\nSecond": "Two lines" });
  expect(result.status, result.stderr + result.stdout).toBe(0);
});

it("accepts complete locale-specific plural forms and rejects incomplete ones", () => {
  const source = 't("Items", { count: 2 });';
  const en = { Items_one: "One item", Items_other: "{{count}} items" };
  expect(runAudit(source, en, { Items_other: "{{count}} 项" }).status).toBe(0);
  expect(runAudit(source, { Items_one: "One item" }, { Items_other: "{{count}} 项" }).status).toBe(1);
});
