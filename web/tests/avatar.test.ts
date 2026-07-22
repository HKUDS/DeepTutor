import test from "node:test";
import assert from "node:assert/strict";

import {
  AVATAR_COLOR_NAMES,
  AVATAR_COLORS,
  AVATAR_ICON_NAMES,
  fallbackAvatarFor,
  parseAvatarMarker,
} from "../lib/avatar";

test("icon and color tables are well-formed", () => {
  assert.equal(AVATAR_ICON_NAMES.length, 16);
  assert.equal(AVATAR_COLOR_NAMES.length, 8);
  assert.equal(new Set(AVATAR_ICON_NAMES).size, AVATAR_ICON_NAMES.length);
  for (const name of AVATAR_ICON_NAMES) {
    assert.match(name, /^[a-z0-9-]+$/);
  }
  for (const hex of Object.values(AVATAR_COLORS)) {
    assert.match(hex, /^#[0-9a-f]{6}$/);
  }
});

test("fallbackAvatarFor is deterministic and always valid", () => {
  for (const username of ["alice", "bob", "局长", "", "a".repeat(200)]) {
    const first = fallbackAvatarFor(username);
    assert.deepEqual(first, fallbackAvatarFor(username));
    assert.ok(AVATAR_ICON_NAMES.includes(first.icon), `icon for ${username}`);
    assert.ok(
      AVATAR_COLOR_NAMES.includes(first.color),
      `color for ${username}`,
    );
  }
});

test("fallback assignment is pinned — a hash change would shuffle every user's avatar", () => {
  // These values are part of the visual contract: users recognise each other
  // by the fallback avatar, so a refactor must not silently reassign them.
  assert.deepEqual(fallbackAvatarFor("alice"), {
    icon: "moon",
    color: "slate",
  });
  assert.deepEqual(fallbackAvatarFor("bob"), { icon: "cloud", color: "rose" });
  assert.deepEqual(fallbackAvatarFor("局长"), {
    icon: "sparkles",
    color: "slate",
  });
  // Empty usernames hash the literal "user" placeholder.
  assert.deepEqual(fallbackAvatarFor(""), { icon: "leaf", color: "pink" });
  assert.deepEqual(fallbackAvatarFor("user"), { icon: "leaf", color: "pink" });
});

test("fallback color index uses an unsigned shift (regression)", () => {
  // "alice" hashes above 2^31; with a signed ">> 4" the color index went
  // negative and the avatar lost its background fill entirely.
  const { color } = fallbackAvatarFor("alice");
  assert.notEqual(AVATAR_COLORS[color], undefined);
});

test("parseAvatarMarker classifies image markers", () => {
  assert.deepEqual(parseAvatarMarker("img:1"), { kind: "image", version: "1" });
  assert.deepEqual(parseAvatarMarker("img:42"), {
    kind: "image",
    version: "42",
  });
});

test("parseAvatarMarker classifies known icon markers", () => {
  assert.deepEqual(parseAvatarMarker("icon:leaf:teal"), {
    kind: "icon",
    icon: "leaf",
    color: "teal",
  });
  assert.deepEqual(parseAvatarMarker(" icon:moon:slate "), {
    kind: "icon",
    icon: "moon",
    color: "slate",
  });
});

test("parseAvatarMarker degrades everything else to the fallback", () => {
  const fallbackInputs = [
    "",
    "   ",
    undefined,
    null,
    "icon:not-a-real-icon:teal",
    "icon:leaf:not-a-color",
    "ICON:Leaf:Teal",
    "icon:leaf",
    "icon:leaf:teal:extra",
    "../etc/passwd",
    "javascript:alert(1)",
  ];
  for (const input of fallbackInputs) {
    assert.deepEqual(
      parseAvatarMarker(input),
      { kind: "fallback" },
      `input: ${String(input)}`,
    );
  }
});
