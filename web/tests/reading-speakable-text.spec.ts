import { describe, expect, it } from "vitest";

import {
  collectSpeakableText,
  rangeForWordIndex,
  speakableFrom,
  wordIndexAtPoint,
  wordIndexForRangeStart,
} from "@/lib/reading-speakable-text";

function article(html: string): HTMLElement {
  const root = document.createElement("article");
  root.innerHTML = html;
  document.body.append(root);
  return root;
}

describe("collectSpeakableText", () => {
  it("enumerates words in document order and joins them for the voice", () => {
    const root = article("<p>Alpha bravo</p><p>charlie delta</p>");
    const model = collectSpeakableText(root);

    expect(model.words.map((w) => w.word)).toEqual([
      "Alpha",
      "bravo",
      "charlie",
      "delta",
    ]);
    // The voice gets plain words, not the markup.
    expect(model.text).toBe("Alpha bravo charlie delta");
  });

  it("strips inline markup down to the words on screen", () => {
    const root = article("<p>The <strong>quick</strong> brown <em>fox</em></p>");
    const model = collectSpeakableText(root);

    expect(model.text).toBe("The quick brown fox");
  });

  it("skips code, which the voice does not read as prose", () => {
    const root = article(
      "<p>Run this</p><pre><code>npm install foo</code></pre><p>then stop</p>",
    );
    const model = collectSpeakableText(root);

    expect(model.words.map((w) => w.word)).toEqual([
      "Run",
      "this",
      "then",
      "stop",
    ]);
  });

  it("keeps punctuation attached so the reader can still be matched", () => {
    const root = article("<p>It costs $12 today.</p>");
    expect(collectSpeakableText(root).words.map((w) => w.word)).toEqual([
      "It",
      "costs",
      "$12",
      "today.",
    ]);
  });

  it("ignores whitespace-only nodes", () => {
    const root = article("<p>one</p>\n   \n<p>two</p>");
    expect(collectSpeakableText(root).text).toBe("one two");
  });
});

describe("wordIndexAtPoint", () => {
  it("finds the word under a caret inside a text node", () => {
    const root = article("<p>Alpha bravo charlie</p>");
    const model = collectSpeakableText(root);
    const node = model.words[0].node;

    expect(wordIndexAtPoint(model, node, 0)).toBe(0);
    expect(wordIndexAtPoint(model, node, 6)).toBe(1);
    expect(wordIndexAtPoint(model, node, 12)).toBe(2);
  });

  it("advances to the next word when the caret sits in the whitespace", () => {
    const root = article("<p>Alpha bravo</p>");
    const model = collectSpeakableText(root);

    // Offset 5 is the space between "Alpha" and "bravo".
    expect(wordIndexAtPoint(model, model.words[0].node, 5)).toBe(1);
  });
});

describe("wordIndexForRangeStart", () => {
  it("maps a selection start onto the word it begins in", () => {
    const root = article("<p>Alpha bravo charlie</p>");
    const model = collectSpeakableText(root);
    const node = model.words[0].node;
    const range = document.createRange();
    range.setStart(node, 6);
    range.setEnd(node, 11);

    expect(wordIndexForRangeStart(model, range)).toBe(1);
  });
});

describe("rangeForWordIndex", () => {
  it("covers exactly one word and nothing around it", () => {
    const root = article("<p>Alpha bravo charlie</p>");
    const model = collectSpeakableText(root);

    expect(rangeForWordIndex(model, 1)?.toString()).toBe("bravo");
    expect(rangeForWordIndex(model, 99)).toBeNull();
  });
});

describe("speakableFrom", () => {
  it("returns the tail of the page and the offset it started at", () => {
    const root = article("<p>Alpha bravo charlie delta</p>");
    const model = collectSpeakableText(root);

    expect(speakableFrom(model, 2)).toEqual({
      text: "charlie delta",
      base: 2,
    });
  });

  it("speaks the whole page when starting at the top", () => {
    const root = article("<p>Alpha bravo</p>");
    const model = collectSpeakableText(root);
    expect(speakableFrom(model, 0)).toEqual({ text: "Alpha bravo", base: 0 });
  });

  it("clamps a start past the end rather than throwing", () => {
    const root = article("<p>Alpha bravo</p>");
    const model = collectSpeakableText(root);
    expect(speakableFrom(model, 99)).toEqual({ text: "", base: 2 });
  });
});
