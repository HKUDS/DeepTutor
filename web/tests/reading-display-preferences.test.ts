import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  DEFAULT_FONT_SIZE,
  DEFAULT_LINE_WIDTH,
  DEFAULT_READER_DISPLAY_PREFERENCES,
  MAX_FONT_SIZE,
  MAX_LINE_WIDTH,
  MIN_FONT_SIZE,
  MIN_LINE_WIDTH,
  normaliseReaderDisplayPreferences,
  readerDisplayShortcut,
} from "../lib/reading-display-preferences";

const reader = readFileSync("components/reading/TextUnitView.tsx", "utf8");
const en = readFileSync("locales/en/app.json", "utf8");
const zh = readFileSync("locales/zh/app.json", "utf8");

test("text reader exposes persistent display preferences", () => {
  assert.match(reader, /dt\.reader\.textPreferences/);
  assert.deepEqual(
    [DEFAULT_FONT_SIZE, MIN_FONT_SIZE, MAX_FONT_SIZE],
    [17, 12, 28],
  );
  assert.deepEqual(
    [DEFAULT_LINE_WIDTH, MIN_LINE_WIDTH, MAX_LINE_WIDTH],
    [84, 48, 104],
  );
  assert.match(reader, /browserStorage\.writeRaw\(\s*"local"/);
});

test("reset includes typography and theme preferences", () => {
  assert.deepEqual(DEFAULT_READER_DISPLAY_PREFERENCES, {
    fontSize: 17,
    lineWidth: 84,
    serif: true,
    readerTheme: "auto",
  });
  assert.match(
    reader,
    /updatePreferences\(DEFAULT_READER_DISPLAY_PREFERENCES\)/,
  );
});

test("stored preferences are bounded and malformed values fall back", () => {
  assert.deepEqual(
    normaliseReaderDisplayPreferences({
      fontSize: 100,
      lineWidth: 3,
      serif: false,
      readerTheme: "night",
    }),
    { fontSize: 28, lineWidth: 48, serif: false, readerTheme: "night" },
  );
  assert.deepEqual(
    normaliseReaderDisplayPreferences({ readerTheme: "invalid" }),
    {
      fontSize: 17,
      lineWidth: 84,
      serif: true,
      readerTheme: "auto",
    },
  );
});

test("keyboard zoom is handled only while the reader is active", () => {
  const input = {
    key: "+",
    modifier: true,
    readerHovered: false,
    readerFocused: false,
  };
  assert.equal(readerDisplayShortcut(input), null);
  assert.equal(
    readerDisplayShortcut({ ...input, readerHovered: true }),
    "increase",
  );
  assert.equal(
    readerDisplayShortcut({ ...input, key: "-", readerFocused: true }),
    "decrease",
  );
  assert.equal(
    readerDisplayShortcut({ ...input, key: "0", readerHovered: true }),
    "reset",
  );
  assert.equal(
    readerDisplayShortcut({ ...input, modifier: false, readerHovered: true }),
    null,
  );
  assert.match(reader, /root\?\.matches\(":hover"\)/);
  assert.match(reader, /root\.contains\(document\.activeElement\)/);
  assert.match(reader, /event\.preventDefault\(\)/);
});

test("reader display copy is translated", () => {
  for (const key of [
    "Smaller text ({{percent}}%)",
    "Larger text ({{percent}}%)",
    "Reset reading display",
    "Use sans-serif font",
    "Use serif font",
    "Change line width ({{width}} characters)",
    "Change reading theme",
  ]) {
    const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    assert.match(en, new RegExp(`"${escaped}": "`));
    assert.match(zh, new RegExp(`"${escaped}": "[^"]+"`));
  }
});

test("the reader's state is spoken by the control that changes it", () => {
  const view = reader;

  // The size and width used to sit in silent spans beside their buttons —
  // visible to a sighted reader, announced to nobody, and reading like debug
  // output. Carrying them in the label means pressing a control says what it
  // did, so the readouts had somewhere to go.
  assert.match(view, /Smaller text \(\{\{percent\}\}%\)/);
  assert.match(view, /Change line width \(\{\{width\}\} characters\)/);
  assert.doesNotMatch(view, /font-mono/);

  // And both translations have to keep the interpolation, or the label reads
  // out the literal placeholder.
  for (const bundle of [en, zh]) {
    assert.match(bundle, /"Smaller text \(\{\{percent\}\}%\)": "[^"]*\{\{percent\}\}/);
    assert.match(
      bundle,
      /"Change line width \(\{\{width\}\} characters\)": "[^"]*\{\{width\}\}/,
    );
  }
});

test("the reader states its position once", () => {
  const pane = readFileSync("components/reading/ReaderPane.tsx", "utf8");
  const view = reader;

  // The header owns it, because it is the only line present in every render
  // mode — a scrolled PDF has no pager to read it off. The paged text view
  // therefore keeps the arrows and drops the sentence, which used to repeat
  // the header's own count 44px underneath it in different words.
  assert.match(pane, /\{\{unit\}\} \{\{n\}\} \/ \{\{total\}\}/);
  assert.doesNotMatch(view, /of \{\{total\}\}/);
  assert.match(view, /Previous \{\{unit\}\}/);
  assert.match(view, /Next \{\{unit\}\}/);
});
