import test from "node:test";
import assert from "node:assert/strict";

import { isStoredCredential } from "@/components/mcp/KeyValueEditor";
import {
  McpApiError,
  getMcpCatalog,
  type McpCatalogField,
} from "../lib/mcp-api";
import {
  appendCatalogPage,
  canInstallEntry,
  catalogCategoryChips,
  catalogInitials,
  describeMcpError,
  filledCredentials,
  localizedCatalogText,
  mcpRefusalKey,
  missingRequiredFields,
  type McpCatalogList,
} from "../lib/mcp-store";

/** Stand-in for `t()`: echoes the key so a mapping is visible in the assert. */
function fakeT(key: string): string {
  return `T:${key}`;
}

function field(patch: Partial<McpCatalogField>): McpCatalogField {
  return {
    key: "api_key",
    label_i18n: { en: "API key" },
    secret: true,
    required: true,
    placeholder: "",
    ...patch,
  };
}

function page(
  ids: string[],
  next_cursor: string,
  total: number,
  categories: Record<string, number> = {},
) {
  return {
    entries: ids.map((id) => ({
      id,
      display_name: id,
      description_i18n: {},
      category: "search",
      tier: "curated",
      transport: "streamableHttp",
      homepage: "",
      docs_url: "",
      requires_i18n: {},
      logo_url: "",
      trust: "verified",
      self_service: true,
      installed: false,
      installed_as: [],
      fields: [],
    })),
    next_cursor,
    total,
    categories,
  };
}

// ── refusal codes ────────────────────────────────────────────────────────

test("every refusal code the per-user API can send maps to its own copy", () => {
  // These are the codes raised in deeptutor/api/routers/space_mcp.py. A code
  // with no mapping degrades to the backend's English sentence, which for
  // "reserved name" or "too many servers" tells the reader nothing actionable.
  for (const code of [
    "mcp.stdio_not_allowed",
    "mcp.blocked_url",
    "mcp.name_reserved",
    "mcp.too_many_servers",
    "mcp.missing_credential",
    "mcp.entry_admin_only",
  ]) {
    const key = mcpRefusalKey(code);
    assert.ok(key, `no message key for ${code}`);
    assert.match(key, /^mcp\.refusal\./);
    const rendered = describeMcpError(
      new McpApiError("raw backend text", code),
      fakeT,
    );
    assert.ok(rendered.startsWith(`T:${key}`), `${code} -> ${rendered}`);
  }
});

test("a blocked URL keeps the backend's diagnosis after the translated sentence", () => {
  // One code covers unresolvable hosts, a non-http scheme and a private-range
  // hit; the reader's next step differs for each, and only the backend text says
  // which happened.
  assert.equal(
    describeMcpError(
      new McpApiError(
        "Cannot resolve hostname: mcp.typo.example",
        "mcp.blocked_url",
      ),
      fakeT,
    ),
    "T:mcp.refusal.blockedUrl Cannot resolve hostname: mcp.typo.example",
  );
});

test("a refusal whose cause is already in the copy does not repeat the raw text", () => {
  assert.equal(
    describeMcpError(
      new McpApiError(
        "At most 8 MCP servers per account",
        "mcp.too_many_servers",
      ),
      fakeT,
    ),
    "T:mcp.refusal.tooManyServers",
  );
});

test("an unmapped refusal keeps the backend's own message", () => {
  // mcp.invalid_name / mcp.no_transport carry the only useful detail (which
  // name, which url), so inventing copy for them would lose information.
  assert.equal(mcpRefusalKey("mcp.no_transport"), null);
  assert.equal(
    describeMcpError(
      new McpApiError(
        "Provide an http(s) URL for the server",
        "mcp.no_transport",
      ),
      fakeT,
    ),
    "Provide an http(s) URL for the server",
  );
  // A transport failure is not a refusal at all.
  assert.equal(
    describeMcpError(new Error("Failed to fetch"), fakeT),
    "Failed to fetch",
  );
  assert.equal(describeMcpError("boom", fakeT), "boom");
});

// ── category chips ───────────────────────────────────────────────────────

test("category chips hide the empty buckets and keep the catalog's order", () => {
  // The backend returns a count for every category in its enum, including the
  // zeros: a chip that opens onto an empty grid is the failure to avoid.
  const chips = catalogCategoryChips({
    search: 6,
    docs: 0,
    code: 2,
    data: 0,
    browser: 1,
    science: 0,
    maps: 0,
    business: 0,
    ai: 0,
    utility: 0,
  });
  assert.deepEqual(chips, [
    { category: "search", count: 6 },
    { category: "code", count: 2 },
    { category: "browser", count: 1 },
  ]);
});

test("a category the frontend has not heard of still gets a chip", () => {
  // The enum lives on the backend; a new bucket must not vanish from the filter
  // just because this list is one release behind.
  const chips = catalogCategoryChips({ search: 1, quantum: 3, docs: 0 });
  assert.deepEqual(chips, [
    { category: "search", count: 1 },
    { category: "quantum", count: 3 },
  ]);
});

// ── credential form ──────────────────────────────────────────────────────

test("a required credential left blank blocks Install", () => {
  const fields = [
    field({ key: "api_key" }),
    field({ key: "team", required: false }),
  ];

  assert.equal(canInstallEntry(fields, {}), false);
  assert.deepEqual(missingRequiredFields(fields, {}), ["api_key"]);
  // Whitespace is blank, matching the backend's strip before it decides a
  // required value is missing.
  assert.equal(canInstallEntry(fields, { api_key: "   " }), false);
  assert.equal(canInstallEntry(fields, { api_key: "sk-1" }), true);
  // The optional field never blocks, filled or not.
  assert.equal(canInstallEntry(fields, { api_key: "sk-1", team: "" }), true);
  assert.deepEqual(missingRequiredFields(fields, { api_key: "sk-1" }), []);
});

test("an entry with no credentials is installable immediately", () => {
  assert.equal(canInstallEntry([], {}), true);
});

test("blank optional values are dropped instead of clearing a stored field", () => {
  // An empty string is the backend's "clear this credential", so sending one for
  // a field the reader simply left alone would wipe it on a reinstall.
  assert.deepEqual(
    filledCredentials({ api_key: "sk-1", team: "  ", plan: "" }),
    {
      api_key: "sk-1",
    },
  );
});

// ── pagination ───────────────────────────────────────────────────────────

test("Load more accumulates pages and stops at the last cursor", () => {
  const first = appendCatalogPage(
    null,
    page(["exa", "tavily"], "2", 5, { search: 5 }),
  );
  assert.deepEqual(
    first.entries.map((entry) => entry.id),
    ["exa", "tavily"],
  );
  assert.equal(first.cursor, "2");

  const second = appendCatalogPage(first, page(["linkup", "jina"], "4", 5));
  assert.deepEqual(
    second.entries.map((entry) => entry.id),
    ["exa", "tavily", "linkup", "jina"],
  );
  assert.equal(second.cursor, "4");

  const third = appendCatalogPage(second, page(["firecrawl"], "", 5));
  assert.equal(third.entries.length, 5);
  assert.equal(third.cursor, "", "an empty next_cursor must retire Load more");
  assert.equal(third.total, 5);
});

test("re-serving a cursor cannot double a row", () => {
  // Two clicks on Load more before the first resolves fetch the same offset.
  const first = appendCatalogPage(null, page(["exa"], "1", 2));
  const twice = appendCatalogPage(
    appendCatalogPage(first, page(["tavily"], "", 2)),
    page(["tavily"], "", 2),
  );
  assert.deepEqual(
    twice.entries.map((entry) => entry.id),
    ["exa", "tavily"],
  );
});

test("a new query restarts the list rather than appending to the old one", () => {
  const previous: McpCatalogList = appendCatalogPage(
    null,
    page(["exa"], "1", 9),
  );
  const fresh = appendCatalogPage(null, page(["maps-co"], "", 1, { maps: 1 }));
  assert.deepEqual(
    fresh.entries.map((entry) => entry.id),
    ["maps-co"],
  );
  assert.equal(fresh.total, 1);
  assert.deepEqual(fresh.categories, { maps: 1 });
  // The old list is untouched — appendCatalogPage never mutates its input.
  assert.equal(previous.entries.length, 1);
});

test("the catalog request carries the filters and the cursor", async () => {
  const calls: string[] = [];
  const original = globalThis.fetch;
  (globalThis as { fetch: typeof fetch }).fetch = async (
    input: RequestInfo | URL,
  ) => {
    calls.push(String(input));
    return new Response(JSON.stringify(page(["exa"], "1", 2, { search: 2 })), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  try {
    let list = appendCatalogPage(
      null,
      await getMcpCatalog("/api/v1/space/mcp", {
        q: "web search",
        category: "search",
        tier: "curated",
        limit: 12,
      }),
    );
    list = appendCatalogPage(
      list,
      await getMcpCatalog("/api/v1/space/mcp", {
        q: "web search",
        category: "search",
        tier: "curated",
        cursor: list.cursor,
        limit: 12,
      }),
    );

    assert.equal(calls.length, 2);
    assert.ok(calls[0].startsWith("/api/v1/space/mcp/catalog?"));
    const first = new URL(calls[0], "http://x").searchParams;
    assert.equal(first.get("q"), "web search");
    assert.equal(first.get("category"), "search");
    assert.equal(first.get("tier"), "curated");
    assert.equal(first.get("limit"), "12");
    assert.equal(
      first.get("cursor"),
      null,
      "the first page must not send a cursor",
    );
    // Page two asks for the offset page one handed back.
    assert.equal(new URL(calls[1], "http://x").searchParams.get("cursor"), "1");
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  }
});

// ── presentation ─────────────────────────────────────────────────────────

test("catalog text degrades from a regional tag to the base language, then English", () => {
  const texts = { en: "Neural web search", zh: "语义网页搜索" };
  assert.equal(localizedCatalogText(texts, "zh-CN"), "语义网页搜索");
  assert.equal(localizedCatalogText(texts, "en-GB"), "Neural web search");
  assert.equal(localizedCatalogText(texts, "fr"), "Neural web search");
  assert.equal(localizedCatalogText({ de: "Suche" }, "fr"), "Suche");
  assert.equal(localizedCatalogText({}, "en"), "");
});

test("initials stand in for the logos the catalog deliberately does not ship", () => {
  assert.equal(catalogInitials("Brave Search"), "BS");
  assert.equal(catalogInitials("Exa"), "EX");
  assert.equal(catalogInitials("jina-ai"), "JA");
  assert.equal(catalogInitials("高德地图"), "高德");
  assert.equal(catalogInitials(""), "?");
});

// ── stored credentials ───────────────────────────────────────────────────

test("a saved credential is recognised as a reference, not as a value", () => {
  // The backend returns `${secret:server/field}` in place of the value, so the
  // editor must render the row as configured. Treating it as editable text
  // would invite saving the placeholder *as* the credential.
  assert.equal(isStoredCredential("${secret:svc/header.Authorization}"), true);
  assert.equal(isStoredCredential("${secret:svc/api_key}"), true);
  assert.equal(isStoredCredential("Bearer sk-live-1"), false);
  assert.equal(isStoredCredential(""), false);
  // Not a whole-value reference: the resolver would not substitute it either.
  assert.equal(isStoredCredential("prefix ${secret:svc/key}"), false);
});
