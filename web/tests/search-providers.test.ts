import test from "node:test";
import assert from "node:assert/strict";

import { searchProviderFields } from "../components/settings/search-providers";
import type { ProviderOption } from "../components/settings/SettingsContext";

// Options as `/api/v1/settings/provider-choices` serves them, derived from the
// backend SEARCH_PROVIDERS spec table. The web app owns no provider table of its
// own, so these fixtures are the contract under test.
const option = (
  value: string,
  label: string,
  extra: Partial<ProviderOption> = {},
): ProviderOption => ({
  value,
  label,
  base_url: "",
  requires_api_key: false,
  requires_base_url: false,
  soft_fallback: true,
  status: "supported",
  ...extra,
});

const OPTIONS: Record<string, ProviderOption> = {
  none: option("none", "None"),
  brave: option("brave", "Brave", { requires_api_key: true }),
  tavily: option("tavily", "Tavily", { requires_api_key: true }),
  jina: option("jina", "Jina", { requires_api_key: true }),
  searxng: option("searxng", "SearXNG", { requires_base_url: true }),
  duckduckgo: option("duckduckgo", "DuckDuckGo"),
  perplexity: option("perplexity", "Perplexity", {
    requires_api_key: true,
    soft_fallback: false,
  }),
  serper: option("serper", "Serper", {
    requires_api_key: true,
    soft_fallback: false,
  }),
  exa: option("exa", "exa", { status: "deprecated" }),
  baidu: option("baidu", "baidu", { status: "deprecated" }),
  openrouter: option("openrouter", "openrouter", { status: "deprecated" }),
};

const ALL_FIELDS = { apiKey: true, baseUrl: true, baseUrlRequired: false };

test("key-based providers show only the API key field", () => {
  for (const provider of ["brave", "tavily", "jina", "perplexity", "serper"]) {
    assert.deepEqual(
      searchProviderFields(provider, OPTIONS[provider]),
      { apiKey: true, baseUrl: false, baseUrlRequired: false },
      `expected ${provider} to require only an API key`,
    );
  }
});

test("searxng shows only a required Base URL", () => {
  assert.deepEqual(searchProviderFields("searxng", OPTIONS.searxng), {
    apiKey: false,
    baseUrl: true,
    baseUrlRequired: true,
  });
});

test("zero-config providers show no connection fields", () => {
  for (const provider of ["duckduckgo", "none"]) {
    assert.deepEqual(
      searchProviderFields(provider, OPTIONS[provider]),
      { apiKey: false, baseUrl: false, baseUrlRequired: false },
      `expected ${provider} to need no credentials`,
    );
  }
});

test("deprecated providers fall back to showing every field", () => {
  for (const provider of ["exa", "baidu", "openrouter"]) {
    assert.deepEqual(
      searchProviderFields(provider, OPTIONS[provider]),
      ALL_FIELDS,
      `expected ${provider} to show all fields`,
    );
  }
});

test("unknown, unloaded, and empty providers fall back to showing every field", () => {
  // Before the choices arrive there is no option to read, and a custom value has
  // no option at all — never hide a control we can't reason about.
  for (const provider of ["custom-thing", "brave", "", null, undefined]) {
    assert.deepEqual(
      searchProviderFields(provider, undefined),
      ALL_FIELDS,
      `expected ${String(provider)} with no option to show all fields`,
    );
  }
  // An option from an older backend that predates the credential flags.
  assert.deepEqual(
    searchProviderFields("brave", { value: "brave", label: "Brave" }),
    ALL_FIELDS,
  );
});

test("a required Base URL is never hidden (baseUrlRequired implies baseUrl)", () => {
  // A field that is mandatory but not rendered would be an unfixable
  // configuration — guard the whole matrix against that state.
  for (const [provider, opt] of Object.entries(OPTIONS)) {
    const fields = searchProviderFields(provider, opt);
    if (fields.baseUrlRequired) {
      assert.ok(
        fields.baseUrl,
        `${provider}: baseUrlRequired must imply baseUrl is shown`,
      );
    }
  }
});

test("searxng is the only provider that requires a Base URL", () => {
  const requiring = Object.entries(OPTIONS)
    .filter(
      ([provider, opt]) => searchProviderFields(provider, opt).baseUrlRequired,
    )
    .map(([provider]) => provider);
  assert.deepEqual(requiring, ["searxng"]);
});
