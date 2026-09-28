import { describe, expect, it } from "vitest";

import { translationTarget } from "@/lib/reading-passage-prompts";
import { selectionTextWithoutLineNumbers } from "@/lib/reading-selection";

describe("translationTarget", () => {
  it("translates into the learner's language unless the passage is in it", () => {
    expect(translationTarget("the slope of the line", "zh-CN")).toBe("zh");
    expect(translationTarget("直线的斜率", "zh")).toBe("en");
    expect(translationTarget("the slope of the line", "en")).toBe("zh");
    expect(translationTarget("直线的斜率", "en")).toBe("en");
    expect(translationTarget("the slope of the line", "fr")).toBe("fr");
  });

  it("does not take Japanese for Chinese", () => {
    expect(translationTarget("線の傾きについて", "zh")).toBe("zh");
  });
});

/** One text-layer span, laid out at `left` px; the column starts at 150. */
function span(text: string, left: number, width = 20): HTMLSpanElement {
  const element = document.createElement("span");
  element.textContent = text;
  element.getBoundingClientRect = () =>
    ({
      left,
      width,
      top: 0,
      height: 10,
      right: left + width,
      bottom: 10,
    }) as DOMRect;
  return element;
}

function page(children: Node[]): HTMLElement {
  const element = document.createElement("div");
  element.append(...children);
  document.body.append(element);
  return element;
}

describe("selectionTextWithoutLineNumbers", () => {
  it("drops margin line numbers and closes a hyphenated break", () => {
    const first = span("while existing RAG systems fall short in", 150, 600);
    const number = span("3", 60);
    const second = span("delivering DeepTu-", 150, 600);
    const next = span("4", 60);
    const third = span("tor, a framework", 150, 600);
    const root = page([
      first,
      document.createElement("br"),
      number,
      document.createElement("br"),
      second,
      document.createElement("br"),
      next,
      document.createElement("br"),
      third,
    ]);
    const range = document.createRange();
    range.setStart(first.firstChild!, 6);
    range.setEnd(third.firstChild!, 4);
    expect(selectionTextWithoutLineNumbers(range)).toBe(
      "existing RAG systems fall short in delivering DeepTu-tor,",
    );
    root.remove();
  });

  it("keeps a number that is part of the text", () => {
    const line = span("See Figure", 150, 600);
    const number = span("3", 400);
    const root = page([line, number]);
    const range = document.createRange();
    range.setStart(line.firstChild!, 0);
    range.setEnd(number.firstChild!, 1);
    expect(selectionTextWithoutLineNumbers(range)).toBeNull();
    root.remove();
  });
});
