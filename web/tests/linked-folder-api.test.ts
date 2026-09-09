import assert from "node:assert/strict";
import test from "node:test";

import {
  linkFolder,
  listLinkedFolders,
  syncLinkedFolder,
  unlinkFolder,
} from "../features/knowledge/api/folders";

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
  globalThis.fetch = handler;
  return () => {
    globalThis.fetch = original;
  };
}

test("linked-folder API methods preserve encoded resource identifiers", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const folder = {
    id: "folder/1",
    path: "/notes",
    added_at: "2026-09-09T10:00:00",
    file_count: 2,
    last_sync: null,
  };
  const restore = stubFetch(async (input, init) => {
    requests.push({ url: String(input), init });
    if (requests.length === 1) return jsonResponse(200, [folder]);
    if (requests.length === 2) return jsonResponse(200, folder);
    if (requests.length === 3) return new Response(null, { status: 204 });
    return jsonResponse(200, {
      message: "Syncing 2 files from linked folder",
      folder_path: "/notes",
      files: [],
      new_files: 1,
      modified_files: 1,
      file_count: 2,
      task_id: "sync-task",
    });
  });

  try {
    assert.deepEqual(
      await listLinkedFolders("Team Notes/2026"),
      [folder],
    );
    assert.deepEqual(await linkFolder("Team Notes/2026", "/notes"), folder);
    await unlinkFolder("Team Notes/2026", "folder/1");
    const result = await syncLinkedFolder("Team Notes/2026", "folder/1");
    assert.equal(result.task_id, "sync-task");
  } finally {
    restore();
  }

  assert.equal(
    requests[0].url,
    "/api/knowledge-bases/Team%20Notes%2F2026/linked-folders",
  );
  assert.equal(
    requests[1].url,
    "/api/knowledge-bases/Team%20Notes%2F2026/link-folder",
  );
  assert.equal(requests[1].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(requests[1].init?.body)), {
    folder_path: "/notes",
  });
  assert.equal(
    requests[2].url,
    "/api/knowledge-bases/Team%20Notes%2F2026/linked-folders/folder%2F1",
  );
  assert.equal(requests[2].init?.method, "DELETE");
  assert.equal(
    requests[3].url,
    "/api/knowledge-bases/Team%20Notes%2F2026/sync-folder/folder%2F1",
  );
  assert.equal(requests[3].init?.method, "POST");
});

test("linked-folder API surfaces backend error details", async () => {
  const restore = stubFetch(async () =>
    jsonResponse(400, { detail: "Path is not a directory" }),
  );
  try {
    await assert.rejects(
      () => linkFolder("kb", "/not-a-folder"),
      /Path is not a directory/,
    );
  } finally {
    restore();
  }
});
