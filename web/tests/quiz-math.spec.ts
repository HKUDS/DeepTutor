import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  normalizeQuizMathText,
  sanitizeMathBlanks,
  wrapBareScriptExpressions,
} from "../lib/quiz-math";

const BARE_FTC = "\\frac{d}{dx}\\int_a^x f(t)\\,dt";
const BLANK_FTC = "$$\\frac{d}{dx}\\int_a^x f(t)\\,dt = \\;____$$";

describe("normalizeQuizMathText", () => {
  it("wraps bare LaTeX command sequences", () => {
    expect(normalizeQuizMathText(BARE_FTC)).toBe(`$${BARE_FTC}$`);
    expect(normalizeQuizMathText("The value \\alpha is large here.")).toBe(
      "The value $\\alpha$ is large here.",
    );
  });

  it("keeps already-delimited maths maths", () => {
    for (const text of [
      "Because $f$ is continuous, $\\int_a^b f(x)\\,dx = F(b)-F(a)$ holds.",
      "$$\\frac{a}{b}$$",
    ]) {
      expect(normalizeQuizMathText(text)).toBe(text);
    }
    // Backslash delimiters are normalised to the `$` form remark-math reads.
    expect(normalizeQuizMathText("\\(\\frac{a}{b}\\)")).toBe("$\\frac{a}{b}$");
    const display = normalizeQuizMathText("\\[\\int_0^1 x\\,dx\\]");
    expect(display).toContain("$$");
    expect(display).toContain("\\int_0^1 x\\,dx");
    expect(display).not.toContain("\\[");
  });

  it("wraps only the formula in mixed prose", () => {
    expect(normalizeQuizMathText("Evaluate \\frac{x}{2} + \\sqrt{y} at x=1.")).toBe(
      "Evaluate $\\frac{x}{2} + \\sqrt{y}$ at x=1.",
    );
  });

  it("turns an underscore blank inside maths into a KaTeX-safe blank", () => {
    const normalized = normalizeQuizMathText(BLANK_FTC);
    expect(normalized).not.toContain("____");
    expect(normalized).toContain("\\underline{\\hspace{2em}}");
    expect(normalized.startsWith("$$")).toBe(true);
    expect(normalized.endsWith("$$")).toBe(true);
  });

  it("sanitizes a blank after wrapping bare maths", () => {
    expect(
      normalizeQuizMathText("\\frac{d}{dx}\\int_a^x f(t)\\,dt = \\;____"),
    ).toBe(
      "$\\frac{d}{dx}\\int_a^x f(t)\\,dt = \\;\\underline{\\hspace{2em}}$",
    );
  });

  it("wraps script-only expressions", () => {
    expect(normalizeQuizMathText("x^{2} + y^{2} = 1")).toContain("^{2}");
    expect(normalizeQuizMathText("f(x)^{2}")).toBe("$f(x)^{2}$");
  });

  it("does not turn currency, prose, paths or code into maths", () => {
    // Currency dollars are escaped rather than paired into a formula; that is
    // the same contract `normalizeMathMarkup` already has for chat text.
    expect(
      normalizeQuizMathText("价格 $100 起，另加 $20 运费和 $5 税。"),
    ).toBe("价格 \\$100 起，另加 \\$20 运费和 $5 税。");
    expect(normalizeQuizMathText("It costs $5 and the value of $x$ is 2.")).toBe(
      "It costs \\$5 and the value of $x$ is 2.",
    );
    for (const text of [
      "Put the file in C:\\Users\\frank\\Desktop and match \\d+.",
      "This is plain prose.",
      "The derivative is f'(a) = lim_{h -> 0} [f(a + h) - f(a)] / h.",
      "```tex\n\\frac{a}{b}\n```",
    ]) {
      expect(normalizeQuizMathText(text)).toBe(text);
    }
    // A code span holding only LaTeX is intentionally promoted by the shared
    // normalizer; genuine code spans such as `npm run dev` stay code.
    expect(normalizeQuizMathText("`\\frac{a}{b}` is a code span")).toBe(
      "$\\frac{a}{b}$ is a code span",
    );
    expect(normalizeQuizMathText("run `npm run dev` first")).toBe(
      "run `npm run dev` first",
    );
  });

  it("is idempotent", () => {
    for (const text of [
      BARE_FTC,
      BLANK_FTC,
      "Evaluate \\frac{x}{2} at x=1.",
      "Let $a_n = \\frac{1}{n}$, so $ \\lim a_n = $ ____.",
      "x^{2} + y^{2} = 1",
      "\\begin{aligned}\na &= b\n\\end{aligned}",
    ]) {
      const once = normalizeQuizMathText(text);
      expect(normalizeQuizMathText(once)).toBe(once);
    }
  });
});

describe("helpers", () => {
  it("sanitizeMathBlanks only touches maths", () => {
    expect(sanitizeMathBlanks("fill this ____ in")).toBe("fill this ____ in");
    expect(sanitizeMathBlanks("$$x = ____$$")).toContain(
      "\\underline{\\hspace{2em}}",
    );
  });

  it("wrapBareScriptExpressions leaves existing maths alone", () => {
    expect(wrapBareScriptExpressions("$x^{2}$")).toBe("$x^{2}$");
  });
});

describe("QuizBlock wiring", () => {
  it("normalizes every rendered quiz field before MarkdownRenderer", () => {
    const source = readFileSync(
      path.join(
        process.cwd(),
        "app/(workspace)/learning/books/components/blocks/QuizBlock.tsx",
      ),
      "utf8",
    );

    for (const marker of [
      "String(question.question",
      "content={normalizeQuizMathText(label)}",
      "content={normalizeQuizMathText(correct)}",
      "String(question.explanation)",
    ]) {
      const index = source.indexOf(marker);
      expect(index, `missing quiz math surface: ${marker}`).toBeGreaterThanOrEqual(
        0,
      );
      const tagStart = source.lastIndexOf("<MarkdownRenderer", index);
      const tagEnd = source.indexOf("/>", index);
      const tag = source.slice(tagStart, tagEnd + 2);
      expect(tag).toContain("normalizeQuizMathText");
      expect(tag).toContain("enableMath");
    }
  });
});