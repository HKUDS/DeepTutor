import test from "node:test";
import assert from "node:assert/strict";

import { searchProviderFields } from "../components/settings/search-providers";

test("key-based providers show only the API key field", () => {
  for (const provider of ["brave", "tavily", "jina", "perplexity", "serper"]) {
    assert.deepEqual(
      searchProviderFields(provider),
      { apiKey: true, baseUrl: false, baseUrlRequired: false },
      `expected ${provider} to require only an API key`,
    );
  }
});

test("searxng shows only a required Base URL", () => {
  assert.deepEqual(searchProviderFields("searxng"), {
    apiKey: false,
    baseUrl: true,
    baseUrlRequired: true,
  });
});

test("zero-config providers show no connection fields", () => {
  for (const provider of ["duckduckgo", "none"]) {
    assert.deepEqual(
      searchProviderFields(provider),
      { apiKey: false, baseUrl: false, baseUrlRequired: false },
      `expected ${provider} to need no credentials`,
    );
  }
});

test("unknown, deprecated, and empty providers fall back to showing every field", () => {
  // Deprecated (exa/baidu/openrouter), a custom value, and no selection must
  // never hide a control we can't reason about.
  for (const provider of [
    "exa",
    "baidu",
    "openrouter",
    "custom-thing",
    "",
    null,
    undefined,
  ]) {
    assert.deepEqual(
      searchProviderFields(provider),
      { apiKey: true, baseUrl: true, baseUrlRequired: false },
      `expected ${String(provider)} to show all fields`,
    );
  }
});

test("provider name is matched case-insensitively and trimmed", () => {
  assert.deepEqual(searchProviderFields("  Brave "), {
    apiKey: true,
    baseUrl: false,
    baseUrlRequired: false,
  });
  assert.deepEqual(searchProviderFields("SearXNG"), {
    apiKey: false,
    baseUrl: true,
    baseUrlRequired: true,
  });
});

// The 8 providers the backend offers in the Search dropdown
// (deeptutor/api/routers/settings.py:_provider_choices) plus a few
// off-list values. Keep in sync if the backend adds a provider.
const ALL_PROVIDERS = [
  "none",
  "brave",
  "tavily",
  "jina",
  "searxng",
  "duckduckgo",
  "perplexity",
  "serper",
  "exa",
  "baidu",
  "openrouter",
  "custom",
  "",
];

test("a required Base URL is never hidden (baseUrlRequired implies baseUrl)", () => {
  // A field that is mandatory but not rendered would be an unfixable
  // configuration — guard the whole matrix against that state.
  for (const provider of ALL_PROVIDERS) {
    const fields = searchProviderFields(provider);
    if (fields.baseUrlRequired) {
      assert.ok(
        fields.baseUrl,
        `${provider}: baseUrlRequired must imply baseUrl is shown`,
      );
    }
  }
});

test("searxng is the only provider that requires a Base URL", () => {
  const requiring = ALL_PROVIDERS.filter(
    (p) => searchProviderFields(p).baseUrlRequired,
  );
  assert.deepEqual(requiring, ["searxng"]);
});
