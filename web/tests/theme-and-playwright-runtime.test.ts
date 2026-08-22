import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (file: string) => readFileSync(path.join(root, file), "utf8");

test("theme initialization runs before hydration", () => {
  const themeSource = read("components/ThemeScript.tsx");
  const layoutSource = read("app/layout.tsx");

  assert.match(themeSource, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(themeSource, /"use client"/);
  assert.doesNotMatch(themeSource, /useEffect/);
  assert.match(layoutSource, /<head>\s*<ThemeScript \/>/);
});

test("browser tests use the product frontend port by default", () => {
  const configSource = read("playwright.config.ts");
  const auditSource = read("tests/e2e/compliance-and-ux.audit.ts");

  assert.match(configSource, /http:\/\/localhost:3782/);
  assert.match(configSource, /--port \$\{BASE_PORT\}/);
  assert.doesNotMatch(configSource, /--port 3000/);
  assert.doesNotMatch(auditSource, /localhost:3000/);
});
