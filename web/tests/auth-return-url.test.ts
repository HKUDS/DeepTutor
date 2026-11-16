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
    search: "?record=record-2",
    hash: "#notes",
  });
  assert.equal(destination, "/notebooks/notes-1?record=record-2#notes");
  assert.equal(
    loginHref(destination),
    "/login?next=%2Fnotebooks%2Fnotes-1%3Frecord%3Drecord-2%23notes",
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

test("login links do not nest an existing next parameter", () => {
  assert.equal(loginHref("/login"), "/login");
  assert.equal(loginHref("/login?registered=1"), "/login");
  assert.equal(loginHref("/login#tools"), "/login");
  assert.equal(
    loginHref("/login?next=%2Flogin%3Fnext%3D%252Flogin"),
    "/login",
  );

  const destination = browserReturnPath({
    pathname: "/login",
    search: "?next=%2Flogin%3Fnext%3D%252Fchat",
  });
  assert.equal(loginHref(destination), "/login");

  assert.equal(
    loginHref("/chat?next=%2Fsecrets&room=1"),
    "/login?next=%2Fchat%3Froom%3D1",
  );
  assert.equal(loginHref(`/${"a".repeat(2000)}`), "/login?next=%2F");
});

test("login inherits a server-invisible fragment without replacing an explicit one", () => {
  assert.equal(inheritLoginHash("/settings", "#tools"), "/settings#tools");
  assert.equal(
    inheritLoginHash("/settings#appearance", "#tools"),
    "/settings#appearance",
  );
});
