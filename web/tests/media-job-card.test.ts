import test from "node:test";
import assert from "node:assert/strict";

import {
  canCancelJob,
  canRetryJob,
  formatJobElapsed,
  hasReclaimableQuota,
  imageJobRefsFromAttachments,
  imageJobRefsFromEvents,
  jobErrorDisplay,
  jobStatusMeta,
  mergeImageJobRefs,
  sanitizeMediaText,
  sortMediaArtifacts,
} from "../lib/media-job-card";
import type { ImageJobStatus, MediaArtifact, MediaJobCard } from "../lib/media-types";

function job(status: ImageJobStatus, extra: Partial<MediaJobCard> = {}): MediaJobCard {
  return {
    id: "j1",
    status,
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
    ...extra,
  };
}

test("every approved job status has a stable non-color label + tone", () => {
  const statuses: ImageJobStatus[] = [
    "queued",
    "running",
    "polling",
    "validating",
    "saving",
    "succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
    "cancelled_unconfirmed",
    "timed_out",
    "unknown",
  ];
  for (const status of statuses) {
    const meta = jobStatusMeta(status);
    assert.ok(meta.labelKey.startsWith("media.status."), status);
    assert.ok(["blue", "amber", "green", "coral"].includes(meta.tone), status);
  }
});

test("queued/running/polling are cancellable; nothing else is", () => {
  assert.ok(canCancelJob("queued"));
  assert.ok(canCancelJob("running"));
  assert.ok(canCancelJob("polling"));
  assert.ok(!canCancelJob("validating"));
  assert.ok(!canCancelJob("saving"));
  assert.ok(!canCancelJob("succeeded"));
  assert.ok(!canCancelJob("failed"));
  assert.ok(!canCancelJob("unknown"));
  assert.ok(!canCancelJob("cancel_requested"));
  assert.ok(!canCancelJob("cancelled"));
});

test("retry is only offered for terminal failure/cancel states (new lineage)", () => {
  for (const status of ["failed", "timed_out", "unknown", "cancelled", "cancelled_unconfirmed"] as const) {
    assert.ok(canRetryJob(status), status);
  }
  for (const status of ["queued", "running", "polling", "validating", "saving", "succeeded", "cancel_requested"] as const) {
    assert.ok(!canRetryJob(status), status);
  }
});

test("elapsed time formats stably without shifting the layout", () => {
  assert.equal(formatJobElapsed(0), "00:00");
  assert.equal(formatJobElapsed(5), "00:05");
  assert.equal(formatJobElapsed(312), "05:12");
  assert.equal(formatJobElapsed(3722), "1h 02m");
  assert.equal(formatJobElapsed(-10), "00:00");
});

test("sanitizeMediaText redacts credentials and base64 payloads", () => {
  assert.ok(!sanitizeMediaText("Authorization: Bearer sk-abc123def456ghi").includes("sk-abc123def456ghi"));
  assert.ok(!sanitizeMediaText("key=sk-abc123def456ghi").includes("sk-abc123def456ghi"));
  assert.equal(
    sanitizeMediaText(`data:image/png;base64,${"A".repeat(80)}`),
    "[redacted]",
  );
  // Ordinary prose is preserved byte-for-byte.
  assert.equal(sanitizeMediaText("a red fox in the snow"), "a red fox in the snow");
});

test("jobErrorDisplay returns sanitized error and never a raw provider body", () => {
  const raw = job("failed", {
    sanitized_error: "provider 401 Authorization: Bearer sk-xyz123456789",
  });
  const text = jobErrorDisplay(raw);
  assert.ok(!text.includes("sk-xyz123456789"));
});

test("image job refs are extracted from attachments and events, deduped", () => {
  const refs = mergeImageJobRefs(
    [
      { type: "image_job", id: "a1", job_id: "job-1" },
      { type: "image_job", job_id: "job-2" },
      { type: "image", url: "/file.png" },
    ],
    [
      { type: "tool_result", metadata: { tool_metadata: { image_jobs: [{ job_id: "job-2" }] } } },
    ] as never[],
  );
  assert.deepEqual(refs.map((r) => r.job_id), ["job-1", "job-2"]);
});

test("imageJobRefsFromAttachments ignores malformed refs", () => {
  assert.deepEqual(imageJobRefsFromAttachments([{ type: "image_job" }]), []);
  assert.deepEqual(imageJobRefsFromAttachments([{ type: "image_job", job_id: "  " }]), []);
  assert.deepEqual(imageJobRefsFromAttachments([{ type: "image", url: "/x.png" }]), []);
});

test("imageJobRefsFromEvents reads only image_jobs tool metadata", () => {
  const refs = imageJobRefsFromEvents([
    { type: "tool_result", metadata: { tool_metadata: { image_jobs: [{ job_id: "job-9" }] } } },
    { type: "tool_result", metadata: { tool_metadata: { artifacts: [{ url: "/x.png" }] } } },
  ] as never[]);
  assert.deepEqual(refs.map((r) => r.job_id), ["job-9"]);
});

// ── artifact management ──────────────────────────────────────────────────────

function artifact(id: string, overrides: Partial<MediaArtifact> = {}): MediaArtifact {
  return {
    id,
    job_id: "j",
    session_id: "s",
    turn_id: "t",
    provider: "openai",
    profile: "img1",
    protocol: "openai_images",
    model: "gpt-image-2",
    operation: "generate",
    original_prompt: "p",
    revised_prompt: "",
    sha256: "hash",
    mime_type: "image/png",
    width: 8,
    height: 8,
    size_bytes: 100,
    created_at: 0,
    gc_candidate_since: 0,
    is_gc_candidate: false,
    reference_count: 0,
    references: [],
    preview_url: null,
    download_url: null,
    ...overrides,
  };
}

test("sortMediaArtifacts sorts by time, size and reference count", () => {
  const list = [
    artifact("a", { created_at: 10, size_bytes: 500, reference_count: 2 }),
    artifact("b", { created_at: 30, size_bytes: 100, reference_count: 5 }),
    artifact("c", { created_at: 20, size_bytes: 900, reference_count: 0 }),
  ];
  assert.deepEqual(sortMediaArtifacts(list, "newest").map((a) => a.id), ["b", "c", "a"]);
  assert.deepEqual(sortMediaArtifacts(list, "oldest").map((a) => a.id), ["a", "c", "b"]);
  assert.deepEqual(sortMediaArtifacts(list, "largest").map((a) => a.id), ["c", "a", "b"]);
  assert.deepEqual(sortMediaArtifacts(list, "refs").map((a) => a.id), ["b", "a", "c"]);
});

test("hasReclaimableQuota reflects eligible cleanup availability", () => {
  assert.ok(hasReclaimableQuota({ reclaimable_bytes: 1 }));
  assert.ok(!hasReclaimableQuota({ reclaimable_bytes: 0 }));
  assert.ok(!hasReclaimableQuota({ reclaimable_bytes: -1 }));
});
