import assert from "node:assert/strict";
import test from "node:test";

import {
  browserReturnPath,
  inheritLoginHash,
  loginHref,
  normalizeInternalReturnPath,
} from "../shared/auth/return-url";

test("return URLs preserve path, query, and fragment", () => {
  const destination = browserReturnPath({
    pathname: "/notebooks/notes-1",
    search: "?course=course-2",
    hash: "#notes",
  });
  assert.equal(destination, "/notebooks/notes-1?course=course-2#notes");
  assert.equal(
    loginHref(destination),
    "/login?next=%2Fnotebooks%2Fnotes-1%3Fcourse%3Dcourse-2%23notes",
  );
});

test("return URLs reject external and ambiguous navigation", () => {
  for (const unsafe of [
    "https://example.com",
    "//example.com/path",
    "/\\example.com/path",
    "/%2f%2fexample.com/path",
    "/chat%0a/next",
    "javascript:alert(1)",
    "/chat\n/next",
  ]) {
    assert.equal(normalizeInternalReturnPath(unsafe), "/", unsafe);
  }
});

test("login inherits a server-invisible fragment without replacing an explicit one", () => {
  assert.equal(inheritLoginHash("/settings", "#tools"), "/settings#tools");
  assert.equal(
    inheritLoginHash("/settings#appearance", "#tools"),
    "/settings#appearance",
  );
});
