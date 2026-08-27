import test from "node:test";
import assert from "node:assert/strict";
import {
  DASHBOARD_GROUPS,
  visibleGroups,
} from "../components/space/SpaceDashboard";

// #963: /whisper ships its pages here but its capability comes from an
// out-of-tree plugin, so a stock install offered a room the backend could not
// start and answered "Unknown capability: whisper_visitor".

const groups = [
  {
    label: { zh: "常规", en: "Regular" },
    items: [{ key: "a", href: "/a" }],
  },
  {
    label: { zh: "更多项目", en: "More Projects" },
    items: [{ key: "w", href: "/w", requiresCapability: "whisper_visitor" }],
  },
] as unknown as typeof DASHBOARD_GROUPS;

test("an installed capability shows its tile", () => {
  const shown = visibleGroups(groups, (name) => name === "whisper_visitor");

  assert.equal(shown.length, 2);
  assert.equal(shown[1].items.length, 1);
});

test("a missing capability hides its tile", () => {
  const shown = visibleGroups(groups, () => false);

  assert.equal(shown.length, 1);
  assert.equal(shown[0].label.en, "Regular");
});

test("a group emptied by the gate loses its heading too", () => {
  // Otherwise "More Projects" renders as a title with nothing under it.
  const shown = visibleGroups(groups, () => false);

  assert.ok(!shown.some((g) => g.label.en === "More Projects"));
});

test("ungated tiles are never affected by the gate", () => {
  for (const gate of [null, () => false, () => true] as const) {
    const shown = visibleGroups(groups, gate);
    assert.equal(shown[0].items[0].key, "a");
  }
});

test("gated tiles stay hidden while the probe is still in flight", () => {
  // Showing them first and removing them a moment later reads as a glitch.
  const shown = visibleGroups(groups, null);

  assert.equal(shown.length, 1);
});

test("the real dashboard gates whisper and nothing else", () => {
  const gated = DASHBOARD_GROUPS.flatMap((g) => g.items).filter(
    (i) => i.requiresCapability,
  );

  assert.deepEqual(
    gated.map((i) => i.requiresCapability),
    ["whisper_visitor"],
  );
});

test("with whisper absent the real dashboard drops More Projects entirely", () => {
  const shown = visibleGroups(DASHBOARD_GROUPS, () => false);

  assert.ok(!shown.some((g) => g.items.some((i) => i.key === "whisper")));
  assert.ok(shown.length > 0, "the ungated groups must survive");
});
