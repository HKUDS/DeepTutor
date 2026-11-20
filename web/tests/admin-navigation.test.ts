import test from "node:test";
import assert from "node:assert/strict";

import { pageSections } from "../components/sidebar/page-sections";

/**
 * `DECISIONS.md` F-1: the admin panel belongs in the navigation for
 * administrators, and must not appear at all for anyone else. A visible entry
 * that always refuses is worse than no entry — it advertises a door the person
 * cannot open and invites them to try.
 *
 * Authorisation itself is enforced in the middleware (`proxy.ts`), not here.
 * These tests cover the display decision only.
 */

const t = (key: string) => key;

function sections(isAdmin: boolean) {
  return pageSections({
    t,
    zh: false,
    allowedSurfaces: null,
    isAvailable: () => true,
    isAdmin,
  });
}

test("an administrator gets an admin section", () => {
  const admin = sections(true).find((section) => section.id === "admin");
  assert.ok(admin, "admin section should exist for an administrator");
  assert.deepEqual(
    admin!.pages.map((page) => page.href),
    ["/admin/users"],
  );
});

test("a non-administrator never sees the admin section", () => {
  assert.equal(
    sections(false).find((section) => section.id === "admin"),
    undefined,
  );
  // Default must be the restrictive one: forgetting to pass `isAdmin` is a
  // programming error that should hide the panel, not expose it.
  const byDefault = pageSections({
    t,
    zh: false,
    allowedSurfaces: null,
    isAvailable: () => true,
  });
  assert.equal(
    byDefault.find((section) => section.id === "admin"),
    undefined,
  );
});

test("the user shelves are unchanged by the admin flag", () => {
  const withAdmin = sections(true).map((section) => section.id);
  const without = sections(false).map((section) => section.id);
  assert.deepEqual(
    without.filter((id) => id !== "admin"),
    withAdmin.filter((id) => id !== "admin"),
  );
  // The admin section is additive: it must not replace or reorder a user shelf.
  assert.equal(withAdmin.filter((id) => id === "home").length, 1);
});

test("every admin entry points at a route that exists", () => {
  // A placeholder entry is allowed by F-1; a *dead* link is not. The admin
  // surface in Phase 1 is exactly one real page, so this stays honest.
  const fs = require("node:fs") as typeof import("node:fs");
  const path = require("node:path") as typeof import("node:path");
  let root = __dirname;
  while (!fs.existsSync(path.join(root, "app"))) {
    const parent = path.dirname(root);
    if (parent === root) throw new Error("web root not found");
    root = parent;
  }
  for (const page of sections(true).find((s) => s.id === "admin")!.pages) {
    const dir = path.join(root, "app", "(admin)", page.href);
    assert.ok(fs.existsSync(path.join(dir, "page.tsx")), `${page.href} has no page.tsx`);
  }
});
