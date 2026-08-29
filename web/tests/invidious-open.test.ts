import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  invidiousFallbackUrl,
  shouldOpenInvidiousInCurrentTab,
} from "../lib/invidious-open";

test("invidiousFallbackUrl keeps a current public feed URL", () => {
  assert.equal(invidiousFallbackUrl("https://inv.example/"), "https://inv.example/feed/popular");
  assert.equal(invidiousFallbackUrl("https://inv.example"), "https://inv.example/feed/popular");
  assert.equal(invidiousFallbackUrl("  "), "");
  assert.equal(invidiousFallbackUrl(undefined), "");
});

test("hub Open Invidious always uses the current tab", () => {
  assert.equal(shouldOpenInvidiousInCurrentTab(true, true), true);
  assert.equal(shouldOpenInvidiousInCurrentTab(true, false), true);
});

test("watch Open Invidious falls back to the current tab when the popup is blocked", () => {
  assert.equal(shouldOpenInvidiousInCurrentTab(false, true), false);
  assert.equal(shouldOpenInvidiousInCurrentTab(false, false), true);
});

test("Invidious hub surfaces Open Invidious status and current-tab navigation", () => {
  const reader = readFileSync(
    path.join(process.cwd(), "components/watching/TimedMediaReader.tsx"),
    "utf8",
  );
  const home = readFileSync(
    path.join(process.cwd(), "components/watching/InvidiousHome.tsx"),
    "utf8",
  );
  assert.match(reader, /openInvidiousRenderer\(undefined, undefined, true\)/);
  assert.match(reader, /openingInvidious=\{openingInvidious\}/);
  assert.match(reader, /fallbackOpenUrl=\{invidiousFallbackUrl\(invidiousPublicUrl\)\}/);
  assert.match(home, /openingInvidious/);
  assert.match(home, /Continue to Invidious/);
  assert.match(home, /disabled=\{openingInvidious\}/);
});

test("Invidious hub offers a host-Chrome YouTube connection", () => {
  const home = readFileSync(
    path.join(process.cwd(), "components/watching/InvidiousHome.tsx"),
    "utf8",
  );
  assert.match(home, /getYouTubeSessionStatus/);
  assert.match(home, /connectYouTubeSession/);
  assert.match(home, /Connect YouTube/);
  assert.match(home, /Disconnect YouTube/);
  assert.match(home, /Using this Mac's existing Chrome session/);
});
