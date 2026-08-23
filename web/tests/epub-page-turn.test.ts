import assert from "node:assert/strict";
import test from "node:test";

import {
  directionForEpubLayout,
  hrefKey,
  locatorForEpubHref,
  resolveEpubPageTurnSwipe,
} from "../lib/epub-page-turn";

test("horizontal swipes turn pages but vertical scrolls do not", () => {
  assert.equal(resolveEpubPageTurnSwipe(200, 100, 100, 105), "next");
  assert.equal(resolveEpubPageTurnSwipe(100, 100, 200, 105), "previous");
  assert.equal(resolveEpubPageTurnSwipe(100, 100, 140, 100), null);
  assert.equal(resolveEpubPageTurnSwipe(100, 100, 160, 180), null);
});

test("RTL reverses physical rendition direction", () => {
  assert.equal(directionForEpubLayout("next", false), "next");
  assert.equal(directionForEpubLayout("next", true), "previous");
  assert.equal(directionForEpubLayout("previous", true), "next");
});

test("source hrefs map to the server locator despite encoding and base paths", () => {
  const refs = [
    { locator: 1, source_href: "OEBPS/chapters/one.xhtml" },
    { locator: 2, source_href: "OEBPS/chapters/two%20words.xhtml" },
  ];
  assert.equal(locatorForEpubHref("OEBPS/chapters/one.xhtml#p1", refs), 1);
  assert.equal(locatorForEpubHref("chapters/two words.xhtml", refs), 2);
  assert.equal(locatorForEpubHref("missing.xhtml", refs), 0);
  assert.equal(hrefKey("./chapter.xhtml#here"), "chapter.xhtml");
});
