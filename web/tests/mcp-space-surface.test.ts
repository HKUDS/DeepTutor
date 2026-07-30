import test from "node:test";
import assert from "node:assert/strict";

import {
  ADMIN_MCP_SURFACE,
  SPACE_MCP_SURFACE,
  loadMcpSurface,
  writeMcpSurface,
} from "../components/mcp/surface";
import { emptyMcpServerConfig, type McpServerConfig } from "../lib/mcp-api";

type Captured = { method: string; url: string; body: unknown };

/** Every write answers with the full state, exactly as the routes do. */
function storeState(servers: Record<string, McpServerConfig>) {
  return {
    servers,
    status: [],
    configured_secrets: {},
    rejected: [],
    deployment: { servers: [], status: [] },
    limits: { max_servers: 8 },
  };
}

function stubFetch(body: unknown): { calls: Captured[]; restore: () => void } {
  const original = globalThis.fetch;
  const calls: Captured[] = [];
  (globalThis as { fetch: typeof fetch }).fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    calls.push({
      method: init?.method ?? "GET",
      url: String(input),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
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

/**
 * Like `stubFetch`, but the first request is refused the way the backend refuses
 * one — `400` with `detail: {code, message}`.
 */
function stubFetchRefusingFirst(
  body: unknown,
  code: string,
): { calls: Captured[]; restore: () => void } {
  const stub = stubFetch(body);
  const passthrough = globalThis.fetch;
  let first = true;
  (globalThis as { fetch: typeof fetch }).fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    const response = await passthrough(input, init);
    if (!first) return response;
    first = false;
    return new Response(JSON.stringify({ detail: { code, message: code } }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  };
  return stub;
}

function remote(url: string): McpServerConfig {
  return { ...emptyMcpServerConfig(), type: "streamableHttp", url };
}

test("the per-user surface reads its own route and keeps the additive fields", async () => {
  const stub = stubFetch({
    servers: { exa: { type: "streamableHttp", url: "https://mcp.exa.ai/mcp" } },
    status: [
      {
        name: "exa",
        transport: "streamableHttp",
        status: "connected",
        error: "",
        tools: [{ name: "web_search", description: "" }],
      },
    ],
    configured_secrets: { exa: ["api_key"] },
    rejected: [{ name: "legacy", reason: "stdio is administrator-only" }],
    deployment: {
      servers: ["shared-docs"],
      status: [
        {
          name: "shared-docs",
          transport: "sse",
          status: "connected",
          error: "",
          tools: [],
        },
      ],
    },
    limits: { max_servers: 8 },
  });
  try {
    const state = await loadMcpSurface(SPACE_MCP_SURFACE);
    // /servers, not the admin registry's bare base path.
    assert.equal(stub.calls[0].url, "/api/v1/space/mcp/servers");
    assert.equal(stub.calls[0].method, "GET");
    assert.ok(state.user);
    // Field names only — the values never leave the backend.
    assert.deepEqual(state.user.configuredSecrets, { exa: ["api_key"] });
    assert.deepEqual(state.user.rejected, [
      { name: "legacy", reason: "stdio is administrator-only" },
    ]);
    assert.deepEqual(state.user.deployment.servers, ["shared-docs"]);
    assert.equal(state.user.deployment.status[0].status, "connected");
    assert.equal(state.user.maxServers, 8);
  } finally {
    stub.restore();
  }
});

test("a missing server cap reads as 0 rather than an invented limit", async () => {
  const stub = stubFetch({ servers: {}, status: [] });
  try {
    const state = await loadMcpSurface(SPACE_MCP_SURFACE);
    assert.equal(state.user?.maxServers, 0);
  } finally {
    stub.restore();
  }
});

test("toggling one server writes only that server", async () => {
  const previous = {
    exa: remote("https://mcp.exa.ai/mcp"),
    tavily: remote("https://mcp.tavily.com/mcp"),
  };
  const next = { ...previous, tavily: { ...previous.tavily, enabled: false } };
  const stub = stubFetch(storeState(next));
  try {
    await writeMcpSurface(SPACE_MCP_SURFACE, previous, next);
    // The untouched server must not be rewritten: each write reconnects the
    // scope, and a whole-map save is how a concurrent edit gets clobbered.
    assert.deepEqual(
      stub.calls.map((call) => `${call.method} ${call.url}`),
      ["PUT /api/v1/space/mcp/servers/tavily"],
    );
    assert.deepEqual(stub.calls[0].body, {
      config: next.tavily,
      secrets: {},
    });
  } finally {
    stub.restore();
  }
});

test("a rename adds the new server before removing the old one", async () => {
  const previous = { exa: remote("https://mcp.exa.ai/mcp") };
  const next = { exa2: remote("https://mcp.exa.ai/mcp") };
  const stub = stubFetch(storeState(next));
  try {
    await writeMcpSurface(SPACE_MCP_SURFACE, previous, next);
    // Order is the point: deleting first would lose the server for good if the
    // add were refused (e.g. at the per-account cap).
    assert.deepEqual(
      stub.calls.map((call) => `${call.method} ${call.url}`),
      [
        "PUT /api/v1/space/mcp/servers/exa2",
        "DELETE /api/v1/space/mcp/servers/exa",
      ],
    );
  } finally {
    stub.restore();
  }
});

test("a refused rename never reaches the delete", async () => {
  const previous = { exa: remote("https://mcp.exa.ai/mcp") };
  const next = { exa2: remote("https://mcp.exa.ai/mcp") };
  // The case the ordering above exists for: at the per-account cap the add is
  // refused, and continuing to the delete would lose the server for good.
  const stub = stubFetchRefusingFirst(storeState(next), "mcp.too_many_servers");
  try {
    await assert.rejects(
      () => writeMcpSurface(SPACE_MCP_SURFACE, previous, next),
      /mcp\.too_many_servers/,
    );
    assert.deepEqual(
      stub.calls.map((call) => `${call.method} ${call.url}`),
      ["PUT /api/v1/space/mcp/servers/exa2"],
    );
  } finally {
    stub.restore();
  }
});

test("a name with URL-significant characters is escaped in the path", async () => {
  const previous = {};
  const next = { "a b": remote("https://example.com/mcp") };
  const stub = stubFetch(storeState({}));
  try {
    await writeMcpSurface(SPACE_MCP_SURFACE, previous, next);
    assert.equal(stub.calls[0].url, "/api/v1/space/mcp/servers/a%20b");
  } finally {
    stub.restore();
  }
});

test("removing the last server still refreshes from the response", async () => {
  const previous = { exa: remote("https://mcp.exa.ai/mcp") };
  const stub = stubFetch(storeState({}));
  try {
    const state = await writeMcpSurface(SPACE_MCP_SURFACE, previous, {});
    assert.deepEqual(
      stub.calls.map((call) => `${call.method} ${call.url}`),
      ["DELETE /api/v1/space/mcp/servers/exa"],
    );
    assert.deepEqual(state.servers, {});
  } finally {
    stub.restore();
  }
});

test("a no-op write re-reads instead of PUTting anything", async () => {
  const previous = { exa: remote("https://mcp.exa.ai/mcp") };
  const stub = stubFetch(storeState(previous));
  try {
    await writeMcpSurface(SPACE_MCP_SURFACE, previous, { ...previous });
    assert.deepEqual(
      stub.calls.map((call) => `${call.method} ${call.url}`),
      ["GET /api/v1/space/mcp/servers"],
    );
  } finally {
    stub.restore();
  }
});

test("the admin registry keeps its whole-map PUT", async () => {
  const previous = { docs: remote("https://example.com/mcp") };
  const next = { ...previous, extra: remote("https://example.com/other") };
  const stub = stubFetch({ status: [] });
  try {
    await writeMcpSurface(ADMIN_MCP_SURFACE, previous, next);
    // Regression guard: the two surfaces have genuinely different write APIs, and
    // sending the per-server shape here would 405 (or worse, half-apply).
    assert.deepEqual(
      stub.calls.map((call) => `${call.method} ${call.url}`),
      ["PUT /api/v1/settings/mcp"],
    );
    assert.deepEqual(stub.calls[0].body, { servers: next });
  } finally {
    stub.restore();
  }
});
