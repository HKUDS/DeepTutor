import test from "node:test";
import assert from "node:assert/strict";

import {
  cancelMediaJob,
  deleteMediaArtifact,
  detachMediaReference,
  fetchMediaArtifact,
  fetchMediaArtifacts,
  fetchMediaJob,
  fetchMediaJobs,
  fetchMediaQuota,
  retryMediaJob,
  runMediaGc,
  submitMediaJob,
} from "../lib/media-api";
import type { MediaJobCard } from "../lib/media-types";

type Captured = { method: string; url: string; body?: unknown };

function stubFetch(
  responder: (captured: Captured, init?: RequestInit) => { status: number; body: unknown },
): () => void {
  const original = globalThis.fetch;
  const captured: Captured[] = [];
  (globalThis as { fetch: typeof fetch }).fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    const url = String(input);
    captured.push({
      method: init?.method ?? "GET",
      url,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    const { status, body } = responder(captured[captured.length - 1], init);
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
  return () => {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  };
}

const JOB: MediaJobCard = {
  id: "job-1",
  status: "queued",
  status_version: 0,
  operation: "generate",
  prompt: "a red fox",
  provider: "openai",
  profile: "img1",
  protocol: "openai_images",
  model: "gpt-image-2",
  session_id: "sess-1",
  turn_id: "turn-1",
  tool_call_id: "tool-1",
  error_code: "",
  sanitized_error: "",
  created_at: 0,
  started_at: 0,
  updated_at: 0,
  finished_at: 0,
  elapsed_seconds: 0,
  poll_after: 0,
  deadline_at: 0,
  attempt_count: 0,
  artifact_ids: [],
  retry_of_job_id: "",
};

test("fetchMediaJob GETs the job card and returns it", async () => {
  const restore = stubFetch(() => ({ status: 200, body: { job: JOB } }));
  try {
    const job = await fetchMediaJob("job-1");
    assert.equal(job.id, "job-1");
    assert.equal(job.status, "queued");
  } finally {
    restore();
  }
});

test("submitMediaJob POSTs a JSON body with the frozen request", async () => {
  const captured: Captured[] = [];
  const restore = stubFetch((c) => {
    captured.push(c);
    return { status: 201, body: { job: { ...JOB, id: "job-new" } } };
  });
  try {
    await submitMediaJob({
      operation: "generate",
      prompt: "a red fox",
      profile: "img1",
      model: "gpt-image-2",
      protocol: "openai_images",
      session_id: "sess-1",
      idempotency_key: "key-1",
    });
  } finally {
    restore();
  }
  assert.equal(captured[0].method, "POST");
  assert.ok(captured[0].url.endsWith("/api/v1/image-jobs"));
  const body = captured[0].body as Record<string, unknown>;
  assert.equal(body.prompt, "a red fox");
  assert.equal(body.idempotency_key, "key-1");
});

test("cancelMediaJob sends the expected status version", async () => {
  const captured: Captured[] = [];
  const restore = stubFetch((c) => {
    captured.push(c);
    return { status: 200, body: { job: { ...JOB, status: "cancel_requested", status_version: 1 } } };
  });
  try {
    const job = await cancelMediaJob("job-1", 0);
    assert.equal(job.status, "cancel_requested");
  } finally {
    restore();
  }
  const body = captured[0].body as Record<string, unknown>;
  assert.equal(body.expected_status_version, 0);
});

test("retryMediaJob sends profile-change overrides for a new lineage", async () => {
  const captured: Captured[] = [];
  const restore = stubFetch((c) => {
    captured.push(c);
    return { status: 201, body: { job: { ...JOB, id: "job-2", profile: "mcp1", protocol: "mcp" } } };
  });
  try {
    const job = await retryMediaJob("job-1", {
      expected_status_version: 3,
      profile: "mcp1",
      model: "",
      protocol: "mcp",
    });
    assert.equal(job.id, "job-2");
  } finally {
    restore();
  }
  const body = captured[0].body as Record<string, unknown>;
  assert.equal(body.profile, "mcp1");
  assert.equal(body.protocol, "mcp");
  assert.equal(body.expected_status_version, 3);
});

test("fetchMediaArtifacts returns artifacts + quota", async () => {
  const restore = stubFetch(() => ({
    status: 200,
    body: {
      artifacts: [],
      quota: { used_bytes: 100, limit_bytes: 1000, reclaimable_bytes: 50, file_count: 1, remaining_bytes: 900 },
    },
  }));
  try {
    const { quota } = await fetchMediaArtifacts();
    assert.equal(quota.reclaimable_bytes, 50);
  } finally {
    restore();
  }
});

test("fetchMediaArtifact GETs a single artifact view", async () => {
  const restore = stubFetch(() => ({
    status: 200,
    body: {
      artifact: {
        id: "art-1",
        job_id: "job-1",
        session_id: "s",
        turn_id: "t",
        provider: "openai",
        profile: "img1",
        protocol: "openai_images",
        model: "gpt-image-2",
        operation: "generate",
        original_prompt: "p",
        revised_prompt: "",
        sha256: "h",
        mime_type: "image/png",
        width: 8,
        height: 8,
        size_bytes: 100,
        created_at: 0,
        gc_candidate_since: 0,
        is_gc_candidate: false,
        reference_count: 1,
        references: [{ id: "r1", owner_type: "session", owner_id: "s", version: 0, created_at: 0, is_live: true }],
        preview_url: "/preview",
        download_url: "/download",
      },
    },
  }));
  try {
    const artifact = await fetchMediaArtifact("art-1");
    assert.equal(artifact.reference_count, 1);
  } finally {
    restore();
  }
});

test("detachMediaReference sends expected_version", async () => {
  const captured: Captured[] = [];
  const restore = stubFetch((c) => {
    captured.push(c);
    return { status: 200, body: { artifact: { id: "art-1" } } };
  });
  try {
    await detachMediaReference("art-1", "ref-1", 2);
  } finally {
    restore();
  }
  assert.equal(captured[0].method, "DELETE");
  const body = captured[0].body as Record<string, unknown>;
  assert.equal(body.expected_version, 2);
});

test("deleteMediaArtifact remove_everywhere sends explicit confirmation", async () => {
  const captured: Captured[] = [];
  const restore = stubFetch((c) => {
    captured.push(c);
    return { status: 200, body: { artifact: { id: "art-1" } } };
  });
  try {
    await deleteMediaArtifact("art-1", { mode: "remove_everywhere", confirmed: true });
  } finally {
    restore();
  }
  const body = captured[0].body as Record<string, unknown>;
  assert.equal(body.mode, "remove_everywhere");
  assert.equal(body.confirmed, true);
});

test("runMediaGc POSTs and returns the result counts", async () => {
  const captured: Captured[] = [];
  const restore = stubFetch((c) => {
    captured.push(c);
    return { status: 200, body: { result: { deleted_count: 3, freed_bytes: 100, scanned_count: 5 } } };
  });
  try {
    const result = await runMediaGc();
    assert.equal(result.deleted_count, 3);
  } finally {
    restore();
  }
  assert.equal(captured[0].method, "POST");
  assert.ok(captured[0].url.endsWith("/api/v1/generated-artifacts/gc"));
});

test("a non-OK response surfaces the sanitized backend detail", async () => {
  const restore = stubFetch(() => ({
    status: 409,
    body: { detail: "remove_everywhere requires explicit confirmation" },
  }));
  try {
    await assert.rejects(
      deleteMediaArtifact("art-1", { mode: "remove_everywhere", confirmed: false }),
      /explicit confirmation/,
    );
  } finally {
    restore();
  }
});

test("fetchMediaJobs reads the jobs list", async () => {
  const restore = stubFetch(() => ({ status: 200, body: { jobs: [JOB] } }));
  try {
    const jobs = await fetchMediaJobs("sess-1");
    assert.equal(jobs.length, 1);
  } finally {
    restore();
  }
});

test("fetchMediaQuota reads the quota summary", async () => {
  const restore = stubFetch(() => ({
    status: 200,
    body: { quota: { used_bytes: 1, limit_bytes: 2, reclaimable_bytes: 0, file_count: 1, remaining_bytes: 1 } },
  }));
  try {
    const quota = await fetchMediaQuota();
    assert.equal(quota.remaining_bytes, 1);
  } finally {
    restore();
  }
});
