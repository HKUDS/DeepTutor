import test from "node:test";
import assert from "node:assert/strict";

import { brandIconFor, brandInitials } from "../lib/brand-icons";
import { BRAND_ICONS } from "../lib/brand-icons.generated";
import { CLI_BRAND_SLUGS, MCP_BRAND_SLUGS, referencedSlugs } from "../lib/brand-slugs";

test("every curated slug is present in the generated data", () => {
  // The generator fails on a missing slug, so this catches the other drift: a
  // curation edit committed without re-running `npm run build:brand-icons`.
  for (const slug of referencedSlugs()) {
    assert.ok(BRAND_ICONS[slug], `${slug} is curated but not generated — re-run the build`);
  }
});

test("the generated data carries nothing the catalogs do not reference", () => {
  // The full Simple Icons set is ~3,450 marks; shipping more than we use would
  // put the rest in the page bundle for nothing.
  const wanted = new Set(referencedSlugs());
  for (const slug of Object.keys(BRAND_ICONS)) {
    assert.ok(wanted.has(slug), `${slug} is generated but unused`);
  }
});

test("every mark is a usable 24x24 path", () => {
  for (const [slug, icon] of Object.entries(BRAND_ICONS)) {
    assert.match(icon.path, /^[Mm]/, `${slug} path does not start with a move`);
    assert.match(icon.hex, /^[0-9A-Fa-f]{6}$/, `${slug} hex is malformed`);
    assert.ok(icon.title.length > 0, `${slug} has no title`);
  }
});

test("a known entry resolves in its own namespace only", () => {
  // `exa` is a hosted search MCP *and* an installed CLI; they are different
  // products, so one namespace's curation must not answer for the other.
  assert.ok(brandIconFor("mcp", "github"));
  assert.equal(brandIconFor("cli", "github"), null);
  assert.ok(brandIconFor("cli", "blender"));
  assert.equal(brandIconFor("mcp", "blender"), null);
});

test("an unknown entry resolves to null rather than a wrong logo", () => {
  // Partial coverage is the design: the newer MCP brands are not in Simple Icons,
  // and a plausible-but-wrong mark is worse than a monogram.
  assert.equal(brandIconFor("mcp", "tavily"), null);
  assert.equal(brandIconFor("mcp", "definitely-not-a-service"), null);
});

test("a renamed install still finds its mark", () => {
  // The MCP store lets the installer choose a local name, and the common edits
  // are case and separator changes.
  assert.ok(brandIconFor("mcp", "GitHub"));
  assert.ok(brandIconFor("mcp", "google_maps"));
  assert.ok(brandIconFor("cli", "OBS_Studio"));
  assert.ok(brandIconFor("cli", "blender-cli"), "a -cli suffix is not part of the brand");
});

test("resolution never throws on junk", () => {
  for (const value of ["", "   ", "../etc/passwd", "-", "___"]) {
    assert.doesNotThrow(() => brandIconFor("cli", value));
  }
});

test("the two namespaces stay in sync with what is generated", () => {
  for (const [namespace, table] of [
    ["mcp", MCP_BRAND_SLUGS],
    ["cli", CLI_BRAND_SLUGS],
  ] as const) {
    for (const id of Object.keys(table)) {
      assert.ok(brandIconFor(namespace, id), `${namespace}:${id} resolves to nothing`);
    }
  }
});

test("initials are word-aware and never empty", () => {
  assert.equal(brandInitials("Google Maps"), "GM");
  assert.equal(brandInitials("firecrawl"), "FI");
  assert.equal(brandInitials("chakra-ui"), "CU");
  assert.equal(brandInitials("Exa"), "EX");
  assert.equal(brandInitials(""), "?");
  assert.equal(brandInitials("   "), "?");
});

test("a CJK name still renders something", () => {
  assert.equal(brandInitials("语雀"), "语雀");
});
