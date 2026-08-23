import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import type { AnnotationItem } from "@/lib/reading-api";
import {
  resolveTextSelectors,
  toRecogitoTextAnnotation,
  toW3CTextAnnotation,
} from "@/lib/reading-w3c-annotations";

const textUnitViewSource = readFileSync(
  path.join(process.cwd(), "components/reading/TextUnitView.tsx"),
  "utf8",
);

function annotation(overrides: Partial<AnnotationItem> = {}): AnnotationItem {
  return {
    annotation_id: "mark-1",
    locator: 1,
    kind: "highlight",
    color: "yellow",
    quote: "portable quote",
    note: "",
    rects: [],
    source_anchor: "",
    author: "user",
    created_at: 1,
    updated_at: 1,
    ...overrides,
  };
}

test("a valid stored position remains the primary selector", () => {
  const selectors = resolveTextSelectors(
    "Start portable quote end",
    annotation({
      selectors: [
        { type: "TextQuoteSelector", exact: "portable quote" },
        { type: "TextPositionSelector", start: 6, end: 20 },
      ],
    }),
  );

  assert.deepEqual(selectors?.[1], {
    type: "TextPositionSelector",
    start: 6,
    end: 20,
  });
});

test("a stale position re-anchors by unique quote", () => {
  const selectors = resolveTextSelectors(
    "A new introduction. portable quote end",
    annotation({
      selectors: [
        { type: "TextQuoteSelector", exact: "portable quote" },
        { type: "TextPositionSelector", start: 0, end: 14 },
      ],
    }),
  );

  assert.deepEqual(selectors?.[1], {
    type: "TextPositionSelector",
    start: 20,
    end: 34,
  });
});

test("prefix and suffix disambiguate repeated Chinese text", () => {
  const selectors = resolveTextSelectors(
    "甲相同文字乙；丙相同文字丁",
    annotation({
      quote: "相同文字",
      selectors: [
        {
          type: "TextQuoteSelector",
          exact: "相同文字",
          prefix: "丙",
          suffix: "丁",
        },
      ],
    }),
  );

  assert.deepEqual(selectors?.[1], {
    type: "TextPositionSelector",
    start: 8,
    end: 12,
  });
});

test("an ambiguous legacy quote stays unresolved instead of marking the wrong text", () => {
  assert.equal(
    resolveTextSelectors(
      "portable quote then portable quote",
      annotation(),
    ),
    null,
  );
});

test("resolved selectors map to both W3C and Recogito annotation contracts", () => {
  const stored = annotation({ note: "remember this", color: "blue" });
  const text = "Start portable quote end";

  const w3c = toW3CTextAnnotation(stored, text, "urn:deeptutor:unit:1");
  const recogito = toRecogitoTextAnnotation(stored, text);

  assert.equal(w3c?.target.source, "urn:deeptutor:unit:1");
  assert.equal(w3c?.body[0].purpose, "commenting");
  assert.equal(recogito?.properties.annotationId, "mark-1");
  assert.equal(recogito?.target.selector[0].start, 6);
});

test("annotation clicks use the Recogito click lifecycle event", () => {
  assert.match(textUnitViewSource, /instance\.on\("clickAnnotation"/);
  assert.doesNotMatch(textUnitViewSource, /instance\.on\("selectionChanged"/);
});
