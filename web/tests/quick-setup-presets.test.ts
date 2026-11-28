import assert from "node:assert/strict";
import test from "node:test";

import {
  findQuickPreset,
  formatFriendlySetupError,
  getQuickProviderGroups,
  pickRecommendedModel,
  resolveQuickPresetRegion,
} from "../lib/quick-setup-presets";

test("getQuickProviderGroups prioritizes domestic vendors for zh and global vendors for non-zh", () => {
  const zh = getQuickProviderGroups("zh-CN");
  assert.deepEqual(
    zh.featured.map((p) => p.id),
    ["deepseek", "dashscope", "siliconflow", "zhipu", "moonshot", "volcengine"],
  );
  assert.ok(zh.more.some((p) => p.id === "minimax"));
  assert.ok(zh.more.some((p) => p.id === "openai"));

  const en = getQuickProviderGroups("en");
  assert.deepEqual(
    en.featured.map((p) => p.id),
    ["openai", "anthropic", "gemini", "openrouter", "deepseek", "custom"],
  );
  assert.ok(en.more.some((p) => p.id === "dashscope"));
});

test("pickRecommendedModel prefers exact recommended match, then substring, then first discovered", () => {
  const deepseek = findQuickPreset("deepseek")!;
  assert.equal(
    pickRecommendedModel(deepseek, ["deepseek-reasoner", "deepseek-chat"]),
    "deepseek-chat",
  );
  assert.equal(
    pickRecommendedModel(deepseek, ["vendor/deepseek-chat-v3", "other"]),
    "vendor/deepseek-chat-v3",
  );
  assert.equal(
    pickRecommendedModel(deepseek, ["custom-model-a", "custom-model-b"]),
    "custom-model-a",
  );
  assert.equal(pickRecommendedModel(deepseek, []), "deepseek-chat");
});

test("MiniMax preset keeps API key console and base URL aligned per region and recommends current models", () => {
  const minimax = findQuickPreset("minimax")!;
  assert.deepEqual(minimax.recommendedModels.slice(0, 2), [
    "MiniMax-M3.1-Flash",
    "MiniMax-M3",
  ]);

  const cnRegion = resolveQuickPresetRegion(minimax, null, "zh-CN");
  assert.equal(cnRegion?.id, "cn");
  assert.equal(cnRegion?.baseUrl, "https://api.minimaxi.com/v1");
  assert.ok(cnRegion?.keyUrl.startsWith("https://platform.minimaxi.com/"));

  const globalRegion = resolveQuickPresetRegion(minimax, null, "en-US");
  assert.equal(globalRegion?.id, "global");
  assert.equal(globalRegion?.baseUrl, "https://api.minimax.io/v1");
  assert.ok(globalRegion?.keyUrl.startsWith("https://platform.minimax.io/"));

  // Explicit region overrides UI locale default.
  const explicitGlobal = resolveQuickPresetRegion(minimax, "global", "zh");
  assert.equal(explicitGlobal?.id, "global");
  assert.equal(explicitGlobal?.baseUrl, "https://api.minimax.io/v1");
});

test("formatFriendlySetupError maps auth, quota, network, access, and fallback failures", () => {
  assert.equal(
    formatFriendlySetupError({ status: "auth_error", models: [], http_status: 401 }).titleKey,
    "quickSetup.error.authTitle",
  );
  assert.equal(
    formatFriendlySetupError(null, "402 insufficient balance").titleKey,
    "quickSetup.error.quotaTitle",
  );
  assert.equal(
    formatFriendlySetupError({ status: "timeout", models: [] }).titleKey,
    "quickSetup.error.networkTitle",
  );
  assert.equal(
    formatFriendlySetupError(null, "HTTP 403 permission denied").titleKey,
    "quickSetup.error.accessTitle",
  );
  assert.equal(
    formatFriendlySetupError(null, "unexpected server error").titleKey,
    "quickSetup.error.genericTitle",
  );
});
