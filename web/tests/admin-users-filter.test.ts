import test from "node:test";
import assert from "node:assert/strict";

import { filterUsersByQuery } from "../lib/admin-users";

function user(username: string): { id: string; username: string } {
  return { id: `u_${username}`, username };
}

const USERS = [user("Alice"), user("bob"), user("alice.smith"), user("Карина")];

test("empty or whitespace-only query returns the list unchanged", () => {
  assert.equal(filterUsersByQuery(USERS, ""), USERS);
  assert.equal(filterUsersByQuery(USERS, "   "), USERS);
});

test("matching is case-insensitive and substring-based", () => {
  assert.deepEqual(
    filterUsersByQuery(USERS, "ALICE").map((u) => u.username),
    ["Alice", "alice.smith"],
  );
  assert.deepEqual(
    filterUsersByQuery(USERS, "smith").map((u) => u.username),
    ["alice.smith"],
  );
});

test("query is trimmed before matching", () => {
  assert.deepEqual(
    filterUsersByQuery(USERS, "  bob  ").map((u) => u.username),
    ["bob"],
  );
});

test("non-latin usernames are searchable", () => {
  assert.deepEqual(
    filterUsersByQuery(USERS, "кари").map((u) => u.username),
    ["Карина"],
  );
});

test("no match yields an empty list, not an error", () => {
  assert.deepEqual(filterUsersByQuery(USERS, "zzz"), []);
  assert.deepEqual(filterUsersByQuery([], "alice"), []);
});
