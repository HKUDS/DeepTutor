import test from "node:test";
import assert from "node:assert/strict";

import {
  toolAvailabilityCopy,
  toolEffectiveEnabled,
} from "../lib/tool-availability";

test("configured runtime and saved preference are both required", () => {
  assert.equal(toolEffectiveEnabled(true, true, false), true);
  assert.equal(toolEffectiveEnabled(true, false, false), false);
  assert.equal(toolEffectiveEnabled(false, true, false), false);
  assert.equal(toolEffectiveEnabled(true, true, true), false);
});

test("search provider readiness has actionable bilingual copy", () => {
  assert.deepEqual(
    toolAvailabilityCopy("search_provider_not_configured", "zh"),
    {
      badge: "未配置",
      detail: "请先在搜索设置中选择提供商。DuckDuckGo 无需 API 密钥。",
      href: "/settings#search",
    },
  );
  assert.deepEqual(
    toolAvailabilityCopy("search_provider_not_configured", "en"),
    {
      badge: "Not configured",
      detail:
        "Choose a provider in Search settings first. DuckDuckGo needs no API key.",
      href: "/settings#search",
    },
  );
});
