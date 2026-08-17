import test from "node:test";
import assert from "node:assert/strict";

import {
  BILINGUAL_DUAL_PANE_MIN_CONTAINER_WIDTH_PX,
  breaksDualScrollLink,
  isParagraphSideTap,
  nextReaderToolbarVisible,
  parseBilingualFontFamily,
  parseBilingualFontSize,
  parseBilingualReaderMode,
  parseBilingualTheme,
  paragraphSwipeFromPoints,
  parseStoredBoolean,
  readerShortcutFromKeyboardEvent,
  scrollPaneToGroup,
  supportsDualPaneAtContainerWidth,
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

test("dual pane support follows actual reader container width", () => {
  assert.equal(BILINGUAL_DUAL_PANE_MIN_CONTAINER_WIDTH_PX, 960);
  assert.equal(supportsDualPaneAtContainerWidth(899), false);
  assert.equal(supportsDualPaneAtContainerWidth(960), true);
  assert.equal(supportsDualPaneAtContainerWidth(1024), true);
  assert.equal(supportsDualPaneAtContainerWidth(null), false);
  assert.equal(supportsDualPaneAtContainerWidth(Number.NaN), false);
});

test("manual drag breaks dual-pane scroll linkage", () => {
  assert.equal(breaksDualScrollLink({ dx: 7, dy: 0 }), false);
  assert.equal(breaksDualScrollLink({ dx: 0, dy: 8 }), true);
  assert.equal(breaksDualScrollLink({ dx: 6, dy: 6 }), true);
  assert.equal(breaksDualScrollLink({ type: "wheel" }), true);
});

test("paragraph side tap accepts only same-line space right of text", () => {
  const line = { left: 16, right: 260, top: 100, bottom: 128 };
  assert.equal(isParagraphSideTap({ x: 285, y: 114 }, line), true);
  assert.equal(isParagraphSideTap({ x: 260, y: 114 }, line), false);
  assert.equal(isParagraphSideTap({ x: 285, y: 90 }, line), false);
});

test("center swipes navigate paragraphs while iOS edges stay reserved", () => {
  assert.equal(paragraphSwipeFromPoints({ x: 200, y: 300 }, { x: 120, y: 306 }, 390), "next");
  assert.equal(paragraphSwipeFromPoints({ x: 200, y: 300 }, { x: 280, y: 306 }, 390), "previous");
  assert.equal(paragraphSwipeFromPoints({ x: 20, y: 300 }, { x: 100, y: 306 }, 390), null);
  assert.equal(paragraphSwipeFromPoints({ x: 370, y: 300 }, { x: 290, y: 306 }, 390), null);
  assert.equal(paragraphSwipeFromPoints({ x: 200, y: 300 }, { x: 260, y: 350 }, 390), null);
});

test("mobile toolbar hides on downward scroll and returns on upward scroll", () => {
  assert.equal(nextReaderToolbarVisible(true, 12), false);
  assert.equal(nextReaderToolbarVisible(false, -12), true);
  assert.equal(nextReaderToolbarVisible(true, 2), true);
  assert.equal(nextReaderToolbarVisible(false, -2), false);
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
