import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const webRoot = path.resolve(__dirname, "..", "..", "..");
const repoRoot = path.resolve(webRoot, "..");

function readRepoFile(...segments: string[]) {
  return readFileSync(path.join(repoRoot, ...segments), "utf8");
}

test("desktop window loads the web app directly so native drag regions work", () => {
  const mainSource = readRepoFile("electron", "src", "main", "index.ts");
  const sidebarSource = readRepoFile(
    "web",
    "components",
    "sidebar",
    "SidebarShell.tsx",
  );

  assert.match(mainSource, /getDesktopWebUrl/);
  assert.match(mainSource, /loadURL\(getDesktopWebUrl\(\)\)/);
  assert.doesNotMatch(mainSource, /loadFile\(join\(__dirname,\s*["'][^"']*shell/);
  assert.match(sidebarSource, /__DEEPTUTOR_DESKTOP__/);
  assert.match(sidebarSource, /__DEEPTUTOR_PLATFORM__/);
  assert.match(sidebarSource, /deeptutor\.desktop/);
  assert.match(sidebarSource, /deeptutor\.platform/);
});

test("desktop preload exposes desktop flags before React boots", () => {
  const preloadSource = readRepoFile("electron", "src", "preload", "index.ts");

  assert.match(preloadSource, /__DEEPTUTOR_DESKTOP__/);
  assert.match(preloadSource, /__DEEPTUTOR_PLATFORM__/);
  assert.match(preloadSource, /__DEEPTUTOR_MAXIMIZE__/);
  assert.match(preloadSource, /deeptutor\.desktop/);
  assert.match(preloadSource, /deeptutor\.platform/);
});

test("desktop electron build does not require a separate renderer HTML entry", () => {
  const electronViteSource = readRepoFile("electron", "electron.vite.config.ts");

  assert.doesNotMatch(electronViteSource, /web\/index\.html/);
});

test("macOS desktop sidebar reserves a compact top inset below traffic lights", () => {
  const sidebarSource = readRepoFile(
    "web",
    "components",
    "sidebar",
    "SidebarShell.tsx",
  );

  assert.match(sidebarSource, /data-desktop-drag-region/);
  assert.match(sidebarSource, /WebkitAppRegion:\s*["']drag["']/);
  assert.match(sidebarSource, /h-\[40px\]/);
  assert.match(sidebarSource, /__DEEPTUTOR_MAXIMIZE__/);
});
