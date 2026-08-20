import test from "node:test";
import assert from "node:assert/strict";
import { findQuoteRange } from "../lib/reading-quote-locator";

// A pdf.js text layer splits a line into many spans and keeps the PDF's own
// hard wraps, so these segment arrays mimic what the DOM actually contains.
const SPANS = [
  "Transformers use ",
  "scaled dot-product\n",
  "attention over all ",
  "tokens.",
];

// Regression: a real pdf.js text layer splits at visual line breaks and its
// spans do NOT end with whitespace, so naive concatenation glues the last word
// of one line to the first word of the next ("Sinusoidalpositional"). The
// fixture above happens to end every span with a space, which hid this.
const REAL_LAYER_SPANS = [
  "Positional encoding",
  "Because attention is permutation invariant, order must be injected explicitly. Sinusoidal",
  "positional encodings add a fixed pattern to each embedding, letting the model infer",
  "relative offsets without learning them from scratch.",
];

test("finds a quote across a span boundary that carries no trailing space", () => {
  const found = findQuoteRange(
    REAL_LAYER_SPANS,
    "Sinusoidal positional encodings add a fixed pattern to each embedding",
  );
  assert.ok(found, "quote spanning the un-spaced boundary must be found");
  assert.equal(found.start.segment, 1);
  assert.equal(found.end.segment, 2);
  assert.equal(found.mode, "collapsed");
});

test("a quote wholly inside one un-spaced span still matches", () => {
  const found = findQuoteRange(REAL_LAYER_SPANS, "permutation invariant");
  assert.ok(found);
  assert.equal(found.start.segment, 1);
});

test("CJK still matches across boundaries, where no space belongs", () => {
  // The joining space would break this one, so the no-join pass has to exist.
  const found = findQuoteRange(["本文讨论注意", "力机制的实现"], "注意力机制");
  assert.ok(found);
  assert.equal(found.start.segment, 0);
  assert.equal(found.end.segment, 1);
});

test("finds a quote that spans several spans and a hard wrap", () => {
  const found = findQuoteRange(SPANS, "scaled dot-product attention");
  assert.ok(found);
  assert.equal(found.start.segment, 1);
  assert.equal(found.start.offset, 0);
  assert.equal(found.end.segment, 2);
  assert.equal(found.mode, "collapsed");
});

test("is case-insensitive", () => {
  assert.ok(findQuoteRange(SPANS, "SCALED DOT-PRODUCT"));
});

test("tolerates collapsed whitespace differences in the quote", () => {
  assert.ok(findQuoteRange(SPANS, "scaled   dot-product\n\tattention"));
});

test("softens punctuation the PDF renders differently", () => {
  const spans = ["He said “hello world” loudly"];
  const found = findQuoteRange(spans, '"hello world"');
  assert.ok(found);
  assert.equal(found.mode, "softened");
});

test("softens a dash mismatch", () => {
  const found = findQuoteRange(
    ["a state—of—the—art result"],
    "state-of-the-art",
  );
  assert.ok(found);
});

test("falls back to the longest matching prefix of a drifting quote", () => {
  const spans = [
    "Positional encoding injects order information into the model.",
  ];
  const found = findQuoteRange(
    spans,
    "Positional encoding injects order information and then some words that are not in the document at all",
  );
  assert.ok(found);
  assert.equal(found.mode, "softened");
  assert.equal(found.start.segment, 0);
  assert.equal(found.start.offset, 0);
  // Stops where the document stops agreeing, rather than at a fixed fraction.
  assert.ok(found.end.offset > 40 && found.end.offset < 60);
});

test("a prefix too short to be credible is not highlighted", () => {
  // Only "the " would match — far below the share of the quote required.
  assert.equal(
    findQuoteRange(
      ["the model is described here"],
      "the quick brown fox jumps over the lazy dog repeatedly and often",
    ),
    null,
  );
});

test("returns null rather than guessing when the quote is absent", () => {
  assert.equal(
    findQuoteRange(SPANS, "quantum flux capacitor calibration"),
    null,
  );
});

test("returns null for empty inputs", () => {
  assert.equal(findQuoteRange([], "anything"), null);
  assert.equal(findQuoteRange(SPANS, ""), null);
  assert.equal(findQuoteRange(SPANS, "   "), null);
});

test("a very short quote does not trigger the head fallback", () => {
  // "zzz" is absent; the head fallback needs >= 8 chars, so this must be null
  // rather than matching something arbitrary.
  assert.equal(findQuoteRange(SPANS, "zzz"), null);
});

test("end offset is exclusive, as DOM Range expects", () => {
  const found = findQuoteRange(["abcdef"], "abc");
  assert.ok(found);
  assert.equal(found.start.offset, 0);
  assert.equal(found.end.offset, 3);
});

test("finds a match at the very end of the last segment", () => {
  const found = findQuoteRange(SPANS, "tokens");
  assert.ok(found);
  assert.equal(found.start.segment, 3);
  assert.equal(found.end.offset, 6);
});

test("handles CJK text without whitespace cues", () => {
  const found = findQuoteRange(
    ["本文讨论", "注意力机制的实现细节"],
    "注意力机制",
  );
  assert.ok(found);
  assert.equal(found.start.segment, 1);
});

test("leading and trailing whitespace in segments does not shift the match", () => {
  const found = findQuoteRange(["   ", "  alpha beta  ", "  "], "alpha beta");
  assert.ok(found);
  assert.equal(found.start.segment, 1);
  assert.equal(found.start.offset, 2);
});
