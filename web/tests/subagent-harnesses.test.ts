import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const readWebFile = (...parts: string[]) =>
  readFileSync(path.join(process.cwd(), ...parts), "utf8");

const HARNESSES = [
  { kind: "hermes", route: "hermes", label: "Hermes Agent" },
  { kind: "openclaw", route: "openclaw", label: "OpenClaw" },
  {
    kind: "deepseek_harness",
    route: "deepseek-harness",
    label: "DeepSeek Harness",
  },
] as const;

test("new harnesses are present in connected-agent labels and glyph dispatch", () => {
  const connected = readWebFile("components", "agents", "ConnectedAgents.tsx");
  const icons = readWebFile("components", "agents", "agent-icons.tsx");

  for (const harness of HARNESSES) {
    assert.match(connected, new RegExp(`kind === ["']${harness.kind}["']`));
    assert.match(connected, new RegExp(harness.label));
    assert.match(icons, new RegExp(`kind === ["']${harness.kind}["']`));
  }
});

test("Gemini CLI is retired and agent glyphs use official local assets", () => {
  const connected = readWebFile("components", "agents", "ConnectedAgents.tsx");
  const icons = readWebFile("components", "agents", "agent-icons.tsx");
  const registry = readWebFile(
    "..",
    "deeptutor",
    "services",
    "subagent",
    "registry.py",
  );

  assert.doesNotMatch(connected, /kind === ["']gemini["']/);
  assert.doesNotMatch(registry, /GeminiBackend/);
  const retiredRoute = path.join(
    process.cwd(),
    "app/(utility)/settings/agents/gemini/page.tsx",
  );
  assert.equal(existsSync(retiredRoute), false);

  for (const asset of [
    "kimi.svg",
    "opencode.svg",
    "mimo-code.svg",
    "hermes.svg",
    "openclaw.svg",
    "deepseek-harness.svg",
  ]) {
    assert.ok(
      existsSync(path.join(process.cwd(), "public", "agent-icons", asset)),
      `${asset} official icon asset is missing`,
    );
    assert.match(icons, new RegExp(`/agent-icons/${asset}`));
  }
});

test("new harnesses have settings anchors and category sections", () => {
  const editor = readWebFile(
    "components",
    "settings",
    "SubagentSettingsEditor.tsx",
  );
  const category = readWebFile(
    "features",
    "settings",
    "sections",
    "AgentsSettingsSection.tsx",
  );
  const nav = readWebFile(
    "features",
    "settings",
    "navigation",
    "settings-nav.ts",
  );

  for (const harness of HARNESSES) {
    assert.match(editor, new RegExp(`${harness.kind}: \\{`));
    assert.match(category, new RegExp(`agent-${harness.route}`));
    assert.match(nav, new RegExp(`agent-${harness.route}`));
    assert.match(nav, new RegExp(`/settings#agent-${harness.route}`));
  }
});
