import test from "node:test";
import assert from "node:assert/strict";
import {
  LOCATOR_HREF_PREFIX,
  codeRanges,
  findLocatorCitations,
  linkifyLocatorCitations,
  locatorFromHref,
  locatorLabel,
} from "../lib/reading-citations";

test("parses a single locator citation", () => {
  const found = findLocatorCitations("Attention is all you need [p.12] here.");
  assert.equal(found.length, 1);
  assert.deepEqual(found[0].locators, [12]);
  assert.equal(found[0].raw, "[p.12]");
});

test("parses lists and ranges, sorted and de-duplicated", () => {
  assert.deepEqual(findLocatorCitations("[p.17,12]")[0].locators, [12, 17]);
  assert.deepEqual(findLocatorCitations("[p.12-14]")[0].locators, [12, 13, 14]);
  assert.deepEqual(findLocatorCitations("[p.14-12]")[0].locators, [12, 13, 14]);
  assert.deepEqual(findLocatorCitations("[p.3,3,4]")[0].locators, [3, 4]);
  assert.deepEqual(findLocatorCitations("[p. 12 , 17 ]")[0].locators, [12, 17]);
});

test("accepts en dash and em dash ranges the model may emit", () => {
  assert.deepEqual(findLocatorCitations("[p.2–3]")[0].locators, [2, 3]);
  assert.deepEqual(findLocatorCitations("[p.2—3]")[0].locators, [2, 3]);
});

test("bounds an absurd range instead of expanding it", () => {
  const found = findLocatorCitations("[p.1-100000]");
  assert.ok(found[0].locators.length <= 41);
});

test("ignores brackets that are not locator citations", () => {
  for (const input of [
    "[12]",
    "[page 12]",
    "[p.]",
    "[p.abc]",
    "[web-1]",
    "[0]",
  ]) {
    assert.deepEqual(findLocatorCitations(input), [], input);
  }
});

test("rejects locator zero", () => {
  assert.deepEqual(findLocatorCitations("[p.0]"), []);
});

test("does not touch citations inside inline code", () => {
  const text = "Use `arr[p.12]` as the index.";
  assert.deepEqual(findLocatorCitations(text), []);
  assert.equal(linkifyLocatorCitations(text), text);
});

test("does not touch citations inside fenced code blocks", () => {
  const text = [
    "Look at this:",
    "",
    "```python",
    "x = data[p.12]",
    "```",
    "",
    "Then [p.3].",
  ].join("\n");
  const found = findLocatorCitations(text);
  assert.equal(found.length, 1);
  assert.deepEqual(found[0].locators, [3]);
});

test("handles tilde fences and multiple fences", () => {
  const text = [
    "~~~",
    "a[p.1]",
    "~~~",
    "prose [p.2]",
    "```",
    "b[p.3]",
    "```",
  ].join("\n");
  const found = findLocatorCitations(text);
  assert.deepEqual(
    found.map((c) => c.locators),
    [[2]],
  );
});

test("an unterminated fence swallows the rest, as Markdown does", () => {
  const text = ["```", "x[p.9]", "still code [p.10]"].join("\n");
  assert.deepEqual(findLocatorCitations(text), []);
});

test("codeRanges reports fenced and inline spans in order", () => {
  const ranges = codeRanges("a `b` c\n```\nd\n```\n");
  assert.ok(ranges.length >= 2);
  for (let i = 1; i < ranges.length; i += 1) {
    assert.ok(ranges[i][0] >= ranges[i - 1][0]);
  }
});

test("leaves an existing markdown link label alone", () => {
  const text = "see [p.12](https://example.com) for details";
  assert.deepEqual(findLocatorCitations(text), []);
  assert.equal(linkifyLocatorCitations(text), text);
});

test("linkify rewrites to an anchor the reader can intercept", () => {
  assert.equal(
    linkifyLocatorCitations("Grounded [p.12] claim."),
    `Grounded [p.12](${LOCATOR_HREF_PREFIX}12) claim.`,
  );
});

test("linkify keeps a multi-locator label but targets the first", () => {
  assert.equal(
    linkifyLocatorCitations("Both [p.12,17] agree."),
    `Both [p.12,17](${LOCATOR_HREF_PREFIX}12) agree.`,
  );
});

test("linkify handles several citations in one paragraph", () => {
  assert.equal(
    linkifyLocatorCitations("First [p.1], then [p.2]."),
    `First [p.1](${LOCATOR_HREF_PREFIX}1), then [p.2](${LOCATOR_HREF_PREFIX}2).`,
  );
});

test("linkify drops locators the document cannot have", () => {
  // A link to page 900 of a 12-page PDF is a dead end; plain text is honest.
  assert.equal(
    linkifyLocatorCitations("Claim [p.900].", { maxLocator: 12 }),
    "Claim [p.900].",
  );
  assert.equal(
    linkifyLocatorCitations("Claim [p.3,900].", { maxLocator: 12 }),
    `Claim [p.3](${LOCATOR_HREF_PREFIX}3).`,
  );
});

test("linkify is idempotent", () => {
  const once = linkifyLocatorCitations("Grounded [p.5] claim.");
  assert.equal(linkifyLocatorCitations(once), once);
});

test("linkify leaves text without citations untouched", () => {
  const text = "No citations here at all.";
  assert.equal(linkifyLocatorCitations(text), text);
  assert.equal(linkifyLocatorCitations(""), "");
});

test("locatorFromHref only accepts the reader's own anchors", () => {
  assert.equal(locatorFromHref(`${LOCATOR_HREF_PREFIX}12`), 12);
  assert.equal(locatorFromHref("#references"), null);
  assert.equal(locatorFromHref(`${LOCATOR_HREF_PREFIX}0`), null);
  assert.equal(locatorFromHref(`${LOCATOR_HREF_PREFIX}abc`), null);
  assert.equal(locatorFromHref(null), null);
  assert.equal(locatorFromHref(undefined), null);
});

test("locatorLabel uses the material's own unit word", () => {
  assert.equal(locatorLabel("page", 12), "page 12");
  assert.equal(locatorLabel("chapter", 3), "chapter 3");
  assert.equal(locatorLabel("", 1), "page 1");
});

// ── Absorbing a spelled-out location ────────────────────────────────────────
// A model answering "where is it?" writes the location into the sentence and
// then appends the marker too, leaving two copies. The phrase becomes the link
// and the marker is dropped, so exactly one link survives — in the place the
// reader is already looking.

test("absorbs 'on page 3' and drops the trailing marker", () => {
  assert.equal(
    linkifyLocatorCitations(
      "The section on Positional encoding is located on page 3 of the document [p.3].",
    ),
    `The section on Positional encoding is located on [page 3](${LOCATOR_HREF_PREFIX}3) of the document.`,
  );
});

test("absorbs when the marker sits immediately after the phrase", () => {
  assert.equal(
    linkifyLocatorCitations("It appears on page 7 [p.7]."),
    `It appears on [page 7](${LOCATOR_HREF_PREFIX}7).`,
  );
});

test("absorbs chapter, slide and section wording too", () => {
  assert.equal(
    linkifyLocatorCitations("Discussed in chapter 4 [p.4]."),
    `Discussed in [chapter 4](${LOCATOR_HREF_PREFIX}4).`,
  );
  assert.equal(
    linkifyLocatorCitations("See slide 9 [p.9]."),
    `See [slide 9](${LOCATOR_HREF_PREFIX}9).`,
  );
});

test("absorbs Chinese location wording", () => {
  assert.equal(
    linkifyLocatorCitations("该节位于第 3 页 [p.3]。"),
    `该节位于[第 3 页](${LOCATOR_HREF_PREFIX}3)。`,
  );
  assert.equal(
    linkifyLocatorCitations("见第4章 [p.4]。"),
    `见[第4章](${LOCATOR_HREF_PREFIX}4)。`,
  );
});

test("does not absorb a phrase naming a different locator", () => {
  // "page 5" is not what [p.3] points at, so both stay as they are.
  assert.equal(
    linkifyLocatorCitations("Unlike page 5, this is explained here [p.3]."),
    `Unlike page 5, this is explained here [p.3](${LOCATOR_HREF_PREFIX}3).`,
  );
});

test("does not reach across a sentence boundary", () => {
  assert.equal(
    linkifyLocatorCitations(
      "It is on page 3. A different claim follows [p.3].",
    ),
    `It is on page 3. A different claim follows [p.3](${LOCATOR_HREF_PREFIX}3).`,
  );
});

test("does not absorb from inside code", () => {
  const text = "Set `page 3` in the config, as documented [p.3].";
  assert.equal(
    linkifyLocatorCitations(text),
    `Set \`page 3\` in the config, as documented [p.3](${LOCATOR_HREF_PREFIX}3).`,
  );
});

test("leaves a multi-locator citation as a marker", () => {
  // There is no single phrase for "[p.3,7]" to absorb.
  assert.equal(
    linkifyLocatorCitations("Both places discuss it on page 3 [p.3,7]."),
    `Both places discuss it on page 3 [p.3,7](${LOCATOR_HREF_PREFIX}3).`,
  );
});

test("absorption survives several citations in one answer", () => {
  assert.equal(
    linkifyLocatorCitations("First on page 1 [p.1], then on page 2 [p.2]."),
    `First on [page 1](${LOCATOR_HREF_PREFIX}1), then on [page 2](${LOCATOR_HREF_PREFIX}2).`,
  );
});

test("a marker with no nearby phrase still renders as a marker", () => {
  assert.equal(
    linkifyLocatorCitations(
      "Order is injected explicitly rather than learned [p.3].",
    ),
    `Order is injected explicitly rather than learned [p.3](${LOCATOR_HREF_PREFIX}3).`,
  );
});

test("absorption is still idempotent", () => {
  const once = linkifyLocatorCitations(
    "It is on page 3 of the document [p.3].",
  );
  assert.equal(linkifyLocatorCitations(once), once);
});
