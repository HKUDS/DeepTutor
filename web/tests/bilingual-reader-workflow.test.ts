import test from "node:test";
import assert from "node:assert/strict";

import { bilingualApi, type BilingualPositionInput } from "../lib/immersive-reading-api";

const POSITION: BilingualPositionInput = {
  chapter_index: 2,
  group_index: 7,
  epub_cfi: "epubcfi(/6/4!/4/2)",
  section_href: "chapter-2.xhtml",
  scroll_percent: 42,
  text_fingerprint: "the bright harbour slept",
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

test("bilingual workflow client uses position, bookmark, and navigation contracts", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: URL; method: string; body?: unknown }> = [];
  globalThis.fetch = (async (input, init) => {
    calls.push({
      url: new URL(String(input), "http://localhost"),
      method: init?.method || "GET",
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    });
    return jsonResponse({
      position: { pairing_id: "pair-1" },
      navigation: { current: null, back_stack: [], forward_stack: [] },
      bookmarks: [],
      status: "ok",
    });
  }) as typeof fetch;

  try {
    await bilingualApi.readingPosition("pair-1");
    await bilingualApi.updateReadingPosition("pair-1", POSITION);
    await bilingualApi.bookmarks("pair-1");
    await bilingualApi.addBookmark("pair-1", POSITION, "", "preview");
    await bilingualApi.renameBookmark("pair-1", "bookmark-1", "Chapter 2");
    await bilingualApi.deleteBookmark("pair-1", "bookmark-1");
    await bilingualApi.navigation("pair-1");
    await bilingualApi.recordNavigation("pair-1", POSITION);
    await bilingualApi.navigateBack("pair-1");
    await bilingualApi.navigateForward("pair-1");
  } finally {
    globalThis.fetch = originalFetch;
  }

  const paths = calls.map((call) => call.url.pathname);
  assert.deepEqual(paths, [
    "/api/v1/immersive-reading/bilingual/pair-1/reading-position",
    "/api/v1/immersive-reading/bilingual/pair-1/reading-position",
    "/api/v1/immersive-reading/bilingual/pair-1/bookmarks",
    "/api/v1/immersive-reading/bilingual/pair-1/bookmarks",
    "/api/v1/immersive-reading/bilingual/pair-1/bookmarks/bookmark-1",
    "/api/v1/immersive-reading/bilingual/pair-1/bookmarks/bookmark-1",
    "/api/v1/immersive-reading/bilingual/pair-1/navigation",
    "/api/v1/immersive-reading/bilingual/pair-1/navigation",
    "/api/v1/immersive-reading/bilingual/pair-1/navigation/back",
    "/api/v1/immersive-reading/bilingual/pair-1/navigation/forward",
  ]);
  assert.deepEqual(calls.map((call) => call.method), [
    "GET",
    "PUT",
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "GET",
    "POST",
    "POST",
    "POST",
  ]);
  assert.deepEqual(calls[1].body, POSITION);
  assert.deepEqual(calls[3].body, {
    position: POSITION,
    title: "",
    preview: "preview",
  });
  assert.deepEqual(calls[4].body, { title: "Chapter 2" });
  assert.deepEqual(calls[7].body, POSITION);
});
