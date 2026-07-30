import test from "node:test";
import assert from "node:assert/strict";

import {
  MCP_ADMIN_BASE_PATH,
  arrayToLines,
  buildMcpServerConfig,
  dictToPairs,
  emptyMcpServerConfig,
  getMcpSettings,
  isRemoteMcpTransport,
  isValidMcpServerName,
  linesToArray,
  mcpRowStatus,
  normalizeServerConfig,
  pairsToDict,
  resolveMcpTransport,
  updateMcpSettings,
  type McpServerConfig,
  type McpServerFormDraft,
  type McpStatusRow,
} from "../lib/mcp-api";

type Captured = { url: string; init: RequestInit | undefined };

// Replace global fetch with one that records the request and answers with the
// queued JSON bodies, so a GET → edit → PUT round trip can be inspected.
function stubFetch(bodies: unknown[]): {
  calls: Captured[];
  restore: () => void;
} {
  const original = globalThis.fetch;
  const calls: Captured[] = [];
  let next = 0;
  (globalThis as { fetch: typeof fetch }).fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    calls.push({ url: String(input), init });
    const body = bodies[Math.min(next++, bodies.length - 1)];
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  return {
    calls,
    restore: () => {
      (globalThis as { fetch: typeof fetch }).fetch = original;
    },
  };
}

/** The draft the add/edit form hands to the builder, unchanged by the user. */
function draftFrom(cfg: McpServerConfig): McpServerFormDraft {
  return {
    type: cfg.type,
    command: cfg.command,
    argsText: arrayToLines(cfg.args),
    envPairs: dictToPairs(cfg.env),
    cwd: cfg.cwd,
    url: cfg.url,
    headerPairs: dictToPairs(cfg.headers),
    toolTimeout: cfg.tool_timeout,
    enabledToolsText: arrayToLines(cfg.enabled_tools),
  };
}

test("a hand-written disabled_tools blocklist survives GET → edit → PUT", async () => {
  // Regression guard: the form has no editor for `disabled_tools`, so it used to
  // drop the field entirely and the backend re-defaulted it to [] — silently
  // unblocking tools an operator had blocked by hand.
  const stub = stubFetch([
    {
      servers: {
        docs: {
          type: "streamableHttp",
          url: "https://example.com/mcp",
          enabled_tools: ["*"],
          disabled_tools: ["remove_document"],
          enabled: true,
        },
      },
      status: [],
    },
    { status: [] },
  ]);
  try {
    const settings = await getMcpSettings(MCP_ADMIN_BASE_PATH);
    const loaded = settings.servers.docs;
    assert.deepEqual(loaded.disabled_tools, ["remove_document"]);

    const built = buildMcpServerConfig(draftFrom(loaded), loaded);
    assert.deepEqual(built.disabled_tools, ["remove_document"]);

    await updateMcpSettings(MCP_ADMIN_BASE_PATH, { docs: built });
    const put = stub.calls[1];
    assert.equal(put.url, MCP_ADMIN_BASE_PATH);
    assert.equal(put.init?.method, "PUT");
    const sent = JSON.parse(String(put.init?.body)) as {
      servers: Record<string, McpServerConfig>;
    };
    assert.deepEqual(sent.servers.docs.disabled_tools, ["remove_document"]);
  } finally {
    stub.restore();
  }
});

test("the request path comes from the caller's surface, not a hardcoded base", async () => {
  const stub = stubFetch([{ servers: {}, status: [] }]);
  try {
    await getMcpSettings("/api/v1/space/mcp/servers");
    assert.equal(stub.calls[0].url, "/api/v1/space/mcp/servers");
  } finally {
    stub.restore();
  }
});

test("normalizeServerConfig defaults disabled_tools and coerces its items", () => {
  assert.deepEqual(normalizeServerConfig({}).disabled_tools, []);
  assert.deepEqual(
    normalizeServerConfig({ disabled_tools: ["a", 2] }).disabled_tools,
    ["a", "2"],
  );
  assert.deepEqual(
    normalizeServerConfig({ disabled_tools: "nope" }).disabled_tools,
    [],
  );
});

test("buildMcpServerConfig carries over the fields the form cannot edit", () => {
  const base: McpServerConfig = {
    ...emptyMcpServerConfig(),
    disabled_tools: ["dangerous"],
    enabled: false,
  };
  const built = buildMcpServerConfig(
    { ...draftFrom(base), url: "https://example.com/mcp" },
    base,
  );
  assert.deepEqual(built.disabled_tools, ["dangerous"]);
  assert.equal(built.enabled, false);
  // A copy, not the same array: the caller keeps editing the loaded config.
  assert.notEqual(built.disabled_tools, base.disabled_tools);
});

test("buildMcpServerConfig trims text fields and falls back to enabled_tools=*", () => {
  const base = emptyMcpServerConfig();
  const built = buildMcpServerConfig(
    {
      type: null,
      command: "  npx  ",
      argsText: "-y\n\n  @modelcontextprotocol/server-filesystem  \n",
      envPairs: [{ key: " TOKEN ", value: "abc" }],
      cwd: "  /tmp  ",
      url: "  ",
      headerPairs: [],
      toolTimeout: 45,
      enabledToolsText: "   \n  ",
    },
    base,
  );
  assert.equal(built.command, "npx");
  assert.deepEqual(built.args, [
    "-y",
    "@modelcontextprotocol/server-filesystem",
  ]);
  assert.deepEqual(built.env, { TOKEN: "abc" });
  assert.equal(built.cwd, "/tmp");
  assert.equal(built.url, "");
  assert.equal(built.tool_timeout, 45);
  assert.deepEqual(built.enabled_tools, ["*"]);
});

test("resolveMcpTransport mirrors the backend's resolved_type", () => {
  const cfg = (patch: Partial<McpServerConfig>): McpServerConfig => ({
    ...emptyMcpServerConfig(),
    ...patch,
  });
  // An explicit type always wins, even against a conflicting command/url.
  assert.equal(
    resolveMcpTransport(cfg({ type: "sse", command: "npx" })),
    "sse",
  );
  assert.equal(resolveMcpTransport(cfg({ command: " npx " })), "stdio");
  assert.equal(
    resolveMcpTransport(cfg({ url: "https://example.com/sse" })),
    "sse",
  );
  // Trailing slashes are stripped before the /sse check, as on the backend.
  assert.equal(
    resolveMcpTransport(cfg({ url: "https://example.com/sse//" })),
    "sse",
  );
  assert.equal(
    resolveMcpTransport(cfg({ url: "https://example.com/mcp" })),
    "streamableHttp",
  );
  assert.equal(resolveMcpTransport(cfg({})), null);
  // A command wins over a url when neither is declared, matching the backend.
  assert.equal(
    resolveMcpTransport(
      cfg({ command: "npx", url: "https://example.com/mcp" }),
    ),
    "stdio",
  );

  assert.equal(isRemoteMcpTransport("sse"), true);
  assert.equal(isRemoteMcpTransport("streamableHttp"), true);
  assert.equal(isRemoteMcpTransport("stdio"), false);
  assert.equal(isRemoteMcpTransport(null), false);
});

test("line/array conversion drops blanks and trims each entry", () => {
  assert.deepEqual(linesToArray("  -y \n\n  --port 3000  \n"), [
    "-y",
    "--port 3000",
  ]);
  assert.deepEqual(linesToArray(""), []);
  assert.deepEqual(linesToArray("   \n  "), []);
  assert.equal(arrayToLines(["-y", "pkg"]), "-y\npkg");
  assert.equal(arrayToLines([]), "");
  // Round trip: a textarea's content survives a save/reload cycle.
  assert.deepEqual(linesToArray(arrayToLines(["a", "b"])), ["a", "b"]);
});

test("pair/dict conversion trims keys, drops empty ones, keeps empty values", () => {
  assert.deepEqual(pairsToDict([{ key: "  A  ", value: " 1 " }]), { A: " 1 " });
  assert.deepEqual(pairsToDict([{ key: "   ", value: "x" }]), {});
  assert.deepEqual(pairsToDict([{ key: "A", value: "" }]), { A: "" });
  // Last writer wins on a duplicate key, so a dict edit never loses a row.
  assert.deepEqual(
    pairsToDict([
      { key: "A", value: "1" },
      { key: "A", value: "2" },
    ]),
    { A: "2" },
  );
  assert.deepEqual(dictToPairs({ A: "1", B: "2" }), [
    { key: "A", value: "1" },
    { key: "B", value: "2" },
  ]);
  assert.deepEqual(dictToPairs({}), []);
});

test("the server-name rule matches the backend validator", () => {
  for (const name of ["a", "A1", "my-server", "my_server", "9lives"]) {
    assert.equal(isValidMcpServerName(name), true, name);
  }
  for (const name of [
    "",
    "-leading",
    "_leading",
    "has space",
    "has.dot",
    "has/slash",
    "naïve",
  ]) {
    assert.equal(isValidMcpServerName(name), false, name);
  }
  // 1 + 63 = the 64-character ceiling the backend enforces.
  assert.equal(isValidMcpServerName("a" + "b".repeat(63)), true);
  assert.equal(isValidMcpServerName("a" + "b".repeat(64)), false);
});

test("a disabled server reads Disabled, not a stuck Connecting", () => {
  // Regression guard: disabling a server makes the manager pop the connection
  // before marking it disabled, so no status row is left behind. Deriving the
  // badge from the row alone fell back to "connecting" forever.
  const disabled: McpServerConfig = {
    ...emptyMcpServerConfig(),
    enabled: false,
  };
  const enabled = emptyMcpServerConfig();
  const row = (status: McpStatusRow["status"]): McpStatusRow => ({
    name: "docs",
    transport: "streamableHttp",
    status,
    error: "",
    tools: [],
  });

  assert.equal(mcpRowStatus(disabled, undefined), "disabled");
  // Even a stale row must not outvote the persisted config.
  assert.equal(mcpRowStatus(disabled, row("connected")), "disabled");
  assert.equal(mcpRowStatus(enabled, undefined), "connecting");
  assert.equal(mcpRowStatus(enabled, row("connected")), "connected");
  assert.equal(mcpRowStatus(enabled, row("error")), "error");
});
