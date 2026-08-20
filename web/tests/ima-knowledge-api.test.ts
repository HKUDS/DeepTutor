import assert from "node:assert/strict";
import test from "node:test";

import { setRuntimeAuthEnabled } from "../lib/api";
import {
  connectImaKnowledgeBase,
  listImaKnowledgeBases,
  probeImaKnowledgeBase,
} from "../lib/knowledge-api";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch(
  handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
): () => void {
  const original = globalThis.fetch;
  (globalThis as { fetch: typeof fetch }).fetch = handler;
  return () => {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  };
}

function installWindow(): { redirectedTo: () => string | null } {
  let redirect: string | null = null;
  const location = { pathname: "/knowledge", href: "" };
  Object.defineProperty(location, "href", {
    get: () => redirect ?? "",
    set: (value: string) => {
      redirect = value;
    },
  });
  (globalThis as { window?: unknown }).window = { location };
  return { redirectedTo: () => redirect };
}

function clearWindow(): void {
  delete (globalThis as { window?: unknown }).window;
}

test("listImaKnowledgeBases sends credentials and preserves pagination", async () => {
  const captured: { input: string; init?: RequestInit } = { input: "" };
  const restore = stubFetch(async (input, init) => {
    captured.input = String(input);
    captured.init = init;
    return jsonResponse(200, {
      knowledge_bases: [{ id: "kb-1", name: "Alpha", description: null }],
      next_cursor: "cursor-2",
      is_end: false,
    });
  });
  try {
    const page = await listImaKnowledgeBases({
      clientId: "cid",
      apiKey: "key",
      cursor: "cursor-1",
      limit: 20,
    });

    assert.equal(captured.input, "/api/v1/knowledge/list-ima");
    assert.equal(captured.init?.method, "POST");
    assert.deepEqual(JSON.parse(String(captured.init?.body)), {
      client_id: "cid",
      api_key: "key",
      cursor: "cursor-1",
      limit: 20,
    });
    assert.equal(page.next_cursor, "cursor-2");
    assert.equal(page.is_end, false);
  } finally {
    restore();
  }
});

test("IMA credential rejection stays inline instead of redirecting login", async () => {
  setRuntimeAuthEnabled(true);
  const windowState = installWindow();
  const restore = stubFetch(async () =>
    jsonResponse(401, { detail: "IMA rejected the supplied credentials." }),
  );
  try {
    await assert.rejects(
      listImaKnowledgeBases({ clientId: "cid", apiKey: "private-key" }),
      /IMA rejected the supplied credentials/,
    );
    assert.equal(windowState.redirectedTo(), null);
  } finally {
    restore();
    clearWindow();
    setRuntimeAuthEnabled(false);
  }
});

test("probeImaKnowledgeBase sends the manual knowledge base id", async () => {
  let body: unknown;
  const restore = stubFetch(async (_input, init) => {
    body = JSON.parse(String(init?.body));
    return jsonResponse(200, {
      knowledge_base_id: "kb-1",
      ok: true,
      credentials_ok: true,
      knowledge_base_name: "Alpha",
      description: null,
      error: null,
    });
  });
  try {
    const result = await probeImaKnowledgeBase({
      clientId: "cid",
      apiKey: "key",
      knowledgeBaseId: "kb-1",
    });

    assert.deepEqual(body, {
      client_id: "cid",
      api_key: "key",
      knowledge_base_id: "kb-1",
    });
    assert.equal(result.ok, true);
  } finally {
    restore();
  }
});

test("connectImaKnowledgeBase sends the DeepTutor name and invalidates on success", async () => {
  const captured: { input: string; body: unknown } = { input: "", body: null };
  const restore = stubFetch(async (input, init) => {
    captured.input = String(input);
    captured.body = JSON.parse(String(init?.body));
    return jsonResponse(200, {
      status: "connected",
      name: "Study Notes",
      knowledge_base_id: "kb-1",
      rag_provider: "ima",
    });
  });
  try {
    const result = await connectImaKnowledgeBase({
      name: "Study Notes",
      clientId: "cid",
      apiKey: "key",
      knowledgeBaseId: "kb-1",
    });

    assert.equal(captured.input, "/api/v1/knowledge/connect-ima");
    assert.deepEqual(captured.body, {
      name: "Study Notes",
      client_id: "cid",
      api_key: "key",
      knowledge_base_id: "kb-1",
    });
    assert.equal(result.rag_provider, "ima");
  } finally {
    restore();
  }
});
