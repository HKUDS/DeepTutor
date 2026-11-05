import test from "node:test";
import assert from "node:assert/strict";

import { errorCopy } from "../lib/error-copy";

/** A t() backed by a tiny catalog, mirroring i18next's missing-key behaviour. */
function makeT(catalog: Record<string, string>) {
  return (key: string, options?: Record<string, unknown>) => {
    const entry = catalog[key];
    if (entry === undefined) return key;
    return entry.replace(/\{\{(\w+)\}\}/g, (whole, name) =>
      name in (options ?? {}) ? String(options?.[name]) : whole,
    );
  };
}

const fa = makeT({
  "Login failed": "ورود ناموفق بود",
  "Request failed: {{status}}": "درخواست ناموفق بود (کد {{status}})",
  "Request failed ({{status}}): {{detail}}": "درخواست ناموفق بود (کد {{status}}): {{detail}}",
});

const en = makeT({});

test("catalogued copy renders in the reader's language", () => {
  assert.equal(errorCopy("Login failed", fa), "ورود ناموفق بود");
});

test("generic status patterns are translated with the status kept as data", () => {
  assert.equal(errorCopy("Request failed: 500", fa), "درخواست ناموفق بود (کد 500)");
  assert.equal(
    errorCopy("Request failed (502): upstream exploded", fa),
    "درخواست ناموفق بود (کد 502): upstream exploded",
  );
});

test("uncatalogued copy falls back to the exact incoming string", () => {
  const provider = "Model provider returned 429: slow down";
  assert.equal(errorCopy(provider, fa), provider);
  assert.equal(errorCopy("Failed to fetch", en), "Failed to fetch");
});

test("an English UI sees exactly the strings it saw before", () => {
  assert.equal(errorCopy("Request failed: 500", en), "Request failed: 500");
  assert.equal(
    errorCopy("Request failed (502): upstream exploded", en),
    "Request failed (502): upstream exploded",
  );
  assert.equal(errorCopy("Login failed", en), "Login failed");
});
