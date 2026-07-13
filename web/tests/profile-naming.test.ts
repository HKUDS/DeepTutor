import test from "node:test";
import assert from "node:assert/strict";

import { nextProfileName } from "../components/settings/profile-naming";

test("an auto name (matching the previous provider) tracks the new provider", () => {
  assert.equal(nextProfileName("Brave", "Brave", "Jina"), "Jina");
});

test("an empty name is filled from the new provider", () => {
  assert.equal(nextProfileName("", "Brave", "Jina"), "Jina");
  assert.equal(nextProfileName("   ", "Brave", "Jina"), "Jina");
});

test("a user-customized name is never overwritten", () => {
  assert.equal(nextProfileName("My search", "Brave", "Jina"), "My search");
});

test("never overwrites with an empty provider label (e.g. deselected)", () => {
  assert.equal(nextProfileName("Brave", "Brave", ""), "Brave");
  assert.equal(nextProfileName("My search", "Brave", ""), "My search");
});

test("matching against the previous label ignores surrounding whitespace", () => {
  assert.equal(nextProfileName("  Brave  ", "Brave", "Jina"), "Jina");
  assert.equal(nextProfileName("Brave", "  Brave  ", "Jina"), "Jina");
});

test("a name equal to the new provider is effectively unchanged", () => {
  // Re-selecting the same provider must not corrupt the name.
  assert.equal(nextProfileName("Jina", "Jina", "Jina"), "Jina");
});
