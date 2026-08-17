import test from "node:test";
import assert from "node:assert/strict";

import { immersiveReadingApi } from "../lib/immersive-reading-api";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(url: string | URL | Request): string {
  return url instanceof Request ? url.url : String(url);
}

test("vocabulary list builds optional bilingual source filters", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: requestUrl(url), init });
    return jsonResponse({ entries: [] });
  }) as typeof fetch;

  try {
    await immersiveReadingApi.vocabulary();
    await immersiveReadingApi.vocabulary("document-1", "pairing-1");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(
    calls[0].url.endsWith("/api/v1/immersive-reading/vocabulary"),
    true,
  );
  assert.equal(
    calls[1].url.endsWith(
      "/api/v1/immersive-reading/vocabulary?document_id=document-1&pairing_id=pairing-1",
    ),
    true,
  );
});

test("saving vocabulary sends bilingual source metadata", async () => {
  const originalFetch = globalThis.fetch;
  let body = "";
  globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
    body = String(init?.body);
    return jsonResponse({ entry: {} });
  }) as typeof fetch;

  try {
    await immersiveReadingApi.addWord(
      "bright",
      "The bright harbour slept.",
      "document-1",
      "English Book",
      "Chapter 2",
      {
        pairing_id: "pairing-1",
        chapter_id: "chapter-2",
        chapter_index: 2,
        group_index: 7,
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }

  const payload = JSON.parse(body) as Record<string, unknown>;
  assert.equal(payload.pairing_id, "pairing-1");
  assert.equal(payload.chapter_id, "chapter-2");
  assert.equal(payload.chapter_index, 2);
  assert.equal(payload.group_index, 7);
});

test("review and difficulty calls use their dedicated contracts", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: requestUrl(url), init });
    return jsonResponse({
      entries: [],
      entry: {},
      available: true,
      reason: "",
      words: [],
      distribution: {},
    });
  }) as typeof fetch;

  try {
    await immersiveReadingApi.reviewVocabulary(10);
    await immersiveReadingApi.gradeVocabularyReview("vocab-1", true);
    await immersiveReadingApi.sectionVocabularyDifficulty("document-1", "section-1");
    await immersiveReadingApi.bilingualVocabularyDifficulty("pairing-1", "chapter-1");
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls[0].url.endsWith("/vocabulary/review?limit=10"), true);
  assert.equal(calls[1].url.endsWith("/vocabulary/review/grade"), true);
  assert.deepEqual(JSON.parse(String(calls[1].init?.body)), {
    entry_id: "vocab-1",
    correct: true,
  });
  assert.equal(
    calls[2].url.endsWith(
      "/documents/document-1/sections/section-1/vocabulary-difficulty",
    ),
    true,
  );
  assert.equal(
    calls[3].url.endsWith(
      "/bilingual/pairing-1/section/chapter-1/vocabulary-difficulty",
    ),
    true,
  );
});

test("vocabulary export URLs target csv and apkg endpoints", () => {
  assert.equal(
    immersiveReadingApi.vocabularyExportUrl("csv").endsWith(
      "/vocabulary/export/csv",
    ),
    true,
  );
  assert.equal(
    immersiveReadingApi.vocabularyExportUrl("apkg").endsWith(
      "/vocabulary/export/apkg",
    ),
    true,
  );
});
