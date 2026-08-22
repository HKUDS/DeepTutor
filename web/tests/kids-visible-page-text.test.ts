import test from "node:test";
import assert from "node:assert/strict";

import { getVisiblePageText } from "../lib/kids-learning/visible-page-text";

test("getVisiblePageText returns only paragraphs within the visible viewport", () => {
  // Mock a mini DOM document and window
  const mockP1 = {
    tagName: "P",
    innerText: "Page 1: Plums are in a tree.",
    textContent: "Page 1: Plums are in a tree.",
    getBoundingClientRect: () => ({ left: -800, right: -10, top: 20, bottom: 100, width: 790, height: 80 }),
    closest: () => null,
  };
  const mockP2 = {
    tagName: "P",
    innerText: "Page 2: Mat and Sam get the plums.",
    textContent: "Page 2: Mat and Sam get the plums.",
    getBoundingClientRect: () => ({ left: 20, right: 780, top: 20, bottom: 100, width: 760, height: 80 }),
    closest: () => null,
  };
  const mockP3 = {
    tagName: "P",
    innerText: "Page 3: Are the plums good now?",
    textContent: "Page 3: Are the plums good now?",
    getBoundingClientRect: () => ({ left: 820, right: 1600, top: 20, bottom: 100, width: 780, height: 80 }),
    closest: () => null,
  };

  const mockDoc = {
    body: {
      children: [mockP1, mockP2, mockP3],
      innerText: "Page 1... Page 2... Page 3...",
    },
    documentElement: { clientWidth: 800, clientHeight: 600 },
    querySelectorAll: (selector: string) => {
      if (selector.includes("p")) {
        return [mockP1, mockP2, mockP3];
      }
      return [];
    },
  } as unknown as Document;

  const mockWin = { innerWidth: 800, innerHeight: 600 } as unknown as Window;

  const visibleText = getVisiblePageText(mockDoc, mockWin);
  assert.equal(visibleText, "Page 2: Mat and Sam get the plums.");
});

test("getVisiblePageText handles word-level spans when paragraphs span across columns", () => {
  const span1 = {
    tagName: "SPAN",
    textContent: "Plums",
    nextSibling: { nodeType: 3, nodeValue: " are " },
    getBoundingClientRect: () => ({ left: 20, right: 100, top: 20, bottom: 60, width: 80, height: 40 }),
    closest: () => null,
  };
  const span2 = {
    tagName: "SPAN",
    textContent: "good",
    nextSibling: { nodeType: 3, nodeValue: "! " },
    getBoundingClientRect: () => ({ left: 110, right: 200, top: 20, bottom: 60, width: 90, height: 40 }),
    closest: () => null,
  };
  const span3Offscreen = {
    tagName: "SPAN",
    textContent: "Tomorrow",
    nextSibling: { nodeType: 3, nodeValue: " we will play." },
    getBoundingClientRect: () => ({ left: 900, right: 1050, top: 20, bottom: 60, width: 150, height: 40 }),
    closest: () => null,
  };

  const mockDoc = {
    body: {
      children: [],
      innerText: "Plums are good! Tomorrow we will play.",
    },
    documentElement: { clientWidth: 800, clientHeight: 600 },
    querySelectorAll: (selector: string) => {
      if (selector.includes("data-kids-word")) {
        return [span1, span2, span3Offscreen];
      }
      return [];
    },
  } as unknown as Document;

  const mockWin = { innerWidth: 800, innerHeight: 600 } as unknown as Window;

  const visibleText = getVisiblePageText(mockDoc, mockWin);
  assert.equal(visibleText, "Plums good!");
});

test("getVisiblePageText returns empty string safely on missing document", () => {
  assert.equal(getVisiblePageText(undefined, undefined), "");
});
