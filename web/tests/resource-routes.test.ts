import assert from "node:assert/strict";
import test from "node:test";

import {
  bookRoute,
  decodeResourceSegment,
  knowledgeBaseRoute,
  notebookRoute,
} from "../lib/resource-routes";

test("resource identities are encoded as path segments", () => {
  assert.equal(bookRoute("book one"), "/books/book%20one");
  assert.equal(
    bookRoute("book one", "page/two"),
    "/books/book%20one/pages/page%2Ftwo",
  );
  assert.equal(notebookRoute("notes/一"), "/notebooks/notes%2F%E4%B8%80");
  assert.equal(
    knowledgeBaseRoute("calculus / 微积分"),
    "/knowledge-bases/calculus%20%2F%20%E5%BE%AE%E7%A7%AF%E5%88%86",
  );
});

test("dynamic resource parameters decode back to stored identities", () => {
  assert.equal(
    decodeResourceSegment("%E5%9B%BD%E9%99%85%E5%8C%BB%E7%96%97"),
    "国际医疗",
  );
  assert.equal(decodeResourceSegment("calculus%20%2F%20%E5%BE%AE%E7%A7%AF%E5%88%86"), "calculus / 微积分");
  assert.equal(decodeResourceSegment("100%25%20coverage"), "100% coverage");
  assert.equal(decodeResourceSegment(null), null);
});

test("filters remain query state rather than resource identity", () => {
  assert.equal(notebookRoute(null, "course one"), "/notebooks?course=course%20one");
  assert.equal(
    notebookRoute("notes", "course one"),
    "/notebooks/notes?course=course%20one",
  );
});
