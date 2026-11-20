import { expect, it } from "vitest";
import { displayQuestionBlanks, practiceQuestionMarkdown } from "@/lib/practice-content";

it("shows canonical blanks as underscores without exposing answer IDs", () => {
  expect(displayQuestionBlanks("3.3×0.4{{blank:blank-1}}4.4×0.3")).toBe("3.3×0.4___4.4×0.3");
  expect(displayQuestionBlanks("{{blank:first}} + {{blank:second}}")).toBe("___ + ___");
  expect(displayQuestionBlanks("Original ____ remains")).toBe("Original ____ remains");
});

it("escapes Markdown blanks so they cannot become horizontal rules or emphasis", () => {
  expect(practiceQuestionMarkdown("{{blank:blank-1}}")).toBe("\\_\\_\\_");
});
