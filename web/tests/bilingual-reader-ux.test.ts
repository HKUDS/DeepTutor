import test from "node:test";
import assert from "node:assert/strict";

import {
  parseBilingualFontFamily,
  parseBilingualFontSize,
  parseBilingualReaderMode,
  parseBilingualTheme,
  parseStoredBoolean,
  readerShortcutFromKeyboardEvent,
  scrollPaneToGroup,
  visibleGroupFromElements,
} from "../lib/bilingual-reader-ux";

function keyboard(key: string, init: Partial<KeyboardEvent> = {}) {
  return { key, shiftKey: false, metaKey: false, ctrlKey: false, altKey: false, ...init } as KeyboardEvent;
}

function group(index: number, offsetTop: number, offsetHeight: number) {
  return {
    dataset: { groupIndex: String(index) },
    offsetTop,
    offsetHeight,
  } as unknown as HTMLElement;
}

test("reader mode parser accepts only supported modes", () => {
  assert.equal(parseBilingualReaderMode("inline"), "inline");
  assert.equal(parseBilingualReaderMode("dual"), "dual");
  assert.equal(parseBilingualReaderMode("hover"), "hover");
  assert.equal(parseBilingualReaderMode("unknown"), "inline");
  assert.equal(parseBilingualReaderMode(null), "inline");
});

test("theme parser accepts only supported themes", () => {
  assert.equal(parseBilingualTheme("system"), "system");
  assert.equal(parseBilingualTheme("sepia"), "sepia");
  assert.equal(parseBilingualTheme("dark"), "dark");
  assert.equal(parseBilingualTheme("oled"), "oled");
  assert.equal(parseBilingualTheme("unknown"), "system");
  assert.equal(parseBilingualTheme(null), "system");
});

test("font size and family parsers handle options and fallbacks", () => {
  assert.equal(parseBilingualFontSize("sm"), "sm");
  assert.equal(parseBilingualFontSize("base"), "base");
  assert.equal(parseBilingualFontSize("lg"), "lg");
  assert.equal(parseBilingualFontSize("xl"), "xl");
  assert.equal(parseBilingualFontSize("2xl"), "2xl");
  assert.equal(parseBilingualFontSize("invalid"), "base");
  assert.equal(parseBilingualFontSize(null), "base");

  assert.equal(parseBilingualFontFamily("sans"), "sans");
  assert.equal(parseBilingualFontFamily("serif"), "serif");
  assert.equal(parseBilingualFontFamily("other"), "sans");
  assert.equal(parseBilingualFontFamily(null), "sans");
});

test("click lookup preference parses only explicit true", () => {
  assert.equal(parseStoredBoolean("true"), true);
  assert.equal(parseStoredBoolean("false"), false);
  assert.equal(parseStoredBoolean(null), false);
});

test("visible group follows the first group entering the reading threshold", () => {
  const groups = [
    group(0, 0, 80),
    group(1, 80, 120),
    group(2, 200, 100),
  ];
  assert.equal(visibleGroupFromElements(groups, 130, 600, 0), 1);
  assert.equal(visibleGroupFromElements(groups, 250, 600, 1), 2);
  assert.equal(visibleGroupFromElements([], 0, 600, 4), 4);
});

test("scrollPaneToGroup scrolls to target group with custom margin offset", () => {
  let scrolledTop = -1;
  let scrolledBehavior = "";
  const dummyPane = {
    querySelector: (selector: string) => {
      if (selector === '[data-group-index="2"]') {
        return { offsetTop: 300 } as HTMLElement;
      }
      return null;
    },
    scrollTo: (options: { top: number; behavior: string }) => {
      scrolledTop = options.top;
      scrolledBehavior = options.behavior;
    },
  } as unknown as HTMLElement;

  assert.equal(scrollPaneToGroup(dummyPane, 2, "smooth", 60), true);
  assert.equal(scrolledTop, 240);
  assert.equal(scrolledBehavior, "smooth");

  assert.equal(scrollPaneToGroup(dummyPane, 99), false);
  assert.equal(scrollPaneToGroup(null, 2), false);
});

test("reader shortcuts map to immersive navigation actions", () => {
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("j")), "next-group");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("ArrowDown")), "next-group");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("K")), "previous-group");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("ArrowUp")), "previous-group");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("t")), "toggle-translation");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("d")), "lookup");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("b")), "bookmark");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("p")), "pronounce");
  assert.equal(
    readerShortcutFromKeyboardEvent(keyboard("P", { shiftKey: true })),
    "pronounce-uk",
  );
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("?")), "toggle-shortcuts");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("h")), "toggle-shortcuts");
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("Escape")), "close-modal");
});

test("reader shortcuts do not steal browser or text-entry keys", () => {
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("p", { metaKey: true })), null);
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("d", { ctrlKey: true })), null);
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("b", { altKey: true })), null);
  assert.equal(
    readerShortcutFromKeyboardEvent(keyboard("b"), { modalOpen: true }),
    null,
  );
  assert.equal(readerShortcutFromKeyboardEvent(keyboard("x")), null);
});
