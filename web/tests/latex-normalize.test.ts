import test from "node:test";
import assert from "node:assert/strict";
import {
  hasBareLatexTrigger,
  hasInlineMathCandidate,
  normalizeMathMarkup,
} from "../lib/latex-normalize";
import { hasMarkdownMath } from "../lib/latex";

// ---------------------------------------------------------------------------
// formulas the model did not delimit at all
// ---------------------------------------------------------------------------

test("bare LaTeX in Chinese prose is wrapped", () => {
  assert.equal(
    normalizeMathMarkup("反演律 \\overline{A+B}=\\bar{A}\\bar{B} 必须熟练。"),
    "反演律 $\\overline{A+B}=\\bar{A}\\bar{B}$ 必须熟练。",
  );
  assert.equal(
    normalizeMathMarkup("则 \\frac{a}{b} = c 成立。"),
    "则 $\\frac{a}{b} = c$ 成立。",
  );
  assert.equal(
    normalizeMathMarkup("答案是 \\boxed{42}。"),
    "答案是 $\\boxed{42}$。",
  );
});

test("bare LaTeX stops at the first English word", () => {
  assert.equal(
    normalizeMathMarkup("The value \\alpha is large here."),
    "The value $\\alpha$ is large here.",
  );
});

test("a bare environment is promoted to display math exactly once", () => {
  const result = normalizeMathMarkup(
    "\\begin{aligned}\na &= b \\\\\nc &= d\n\\end{aligned}",
  );

  assert.ok(result.includes("$$\n\\begin{aligned}"));
  assert.ok(
    !result.includes("$\\begin{aligned}$"),
    "the environment must not also be wrapped as inline math",
  );
});

test("bare LaTeX inside a table cell stays inside its cell", () => {
  assert.equal(
    normalizeMathMarkup("| 公式 | 说明 |\n| --- | --- |\n| \\sqrt{x^2+1} | 模长 |"),
    "| 公式 | 说明 |\n| --- | --- |\n| $\\sqrt{x^2+1}$ | 模长 |",
  );
});

// ---------------------------------------------------------------------------
// formulas the model put in a code span
// ---------------------------------------------------------------------------

test("a code span holding only LaTeX becomes maths", () => {
  assert.equal(
    normalizeMathMarkup("反演律 `\\overline{A+B}=\\bar{A}\\bar{B}` 必须熟练。"),
    "反演律 $\\overline{A+B}=\\bar{A}\\bar{B}$ 必须熟练。",
  );
  assert.equal(
    normalizeMathMarkup("公式 `$\\bar{A}$` 如上。"),
    "公式 $\\bar{A}$ 如上。",
  );
});

test("a code span holding code stays code", () => {
  for (const input of [
    "用 `$PATH` 变量。",
    "运行 `npm run dev` 启动。",
    "注意 `a[i] = b + 1` 这一行。",
  ]) {
    assert.equal(normalizeMathMarkup(input), input);
  }
});

// ---------------------------------------------------------------------------
// backslashes that are not maths
// ---------------------------------------------------------------------------

test("paths, regexes and Markdown escapes are left alone", () => {
  for (const input of [
    "把文件放到 C:\\Users\\frank\\Desktop 目录。",
    "用 \\d+ 匹配数字。",
    "字面 \\*星号\\* 与 \\_下划线\\_。",
    "参考文献 \\[1\\] 指出该结论。",
  ]) {
    assert.equal(normalizeMathMarkup(input), input);
  }
});

test("fenced code is never rewritten", () => {
  const input = "```tex\n\\(x+y\\)\n```";
  assert.equal(normalizeMathMarkup(input), input);
});

// ---------------------------------------------------------------------------
// delimiters the model chose instead of $
// ---------------------------------------------------------------------------

test("backslash delimiters become dollars without padding", () => {
  assert.equal(
    normalizeMathMarkup("由此可得 \\( x + y = z \\) 成立。"),
    "由此可得 $x + y = z$ 成立。",
  );
  assert.equal(
    normalizeMathMarkup("由 \\(a\\) 到 \\(b\\)，再到 \\(c\\)。"),
    "由 $a$ 到 $b$，再到 $c$。",
  );
});

test("a doubly-escaped delimiter is repaired", () => {
  assert.equal(
    normalizeMathMarkup("由此可得 \\\\(x+y\\\\) 成立。"),
    "由此可得 $x+y$ 成立。",
  );
});

test("an inline paren formula never merges two table cells", () => {
  const input = "| \\(a | b\\) |\n| --- |\n| x |";
  assert.equal(normalizeMathMarkup(input), input);
});

test("a loose $ pair is tightened rather than dropped", () => {
  assert.equal(
    normalizeMathMarkup("由此 $ x + y $ 成立。"),
    "由此 $x + y$ 成立。",
  );
});

// ---------------------------------------------------------------------------
// dollars that are money
// ---------------------------------------------------------------------------

test("currency is escaped so remark-math cannot swallow it", () => {
  assert.equal(
    normalizeMathMarkup("价格 $100 起，另加 $20 运费和 $5 税。"),
    "价格 \\$100 起，另加 \\$20 运费和 $5 税。",
  );
  assert.equal(
    normalizeMathMarkup("It costs $5 and the value of $x$ is 2."),
    "It costs \\$5 and the value of $x$ is 2.",
  );
});

test("real formulas survive the same pass", () => {
  for (const input of [
    "设 $x^2+y^2=z^2$ 成立。",
    "设 $x$ 为变量，$y$ 为常量。",
    "$\\text{速度} = \\frac{s}{t}$",
    "已知 $速度 = 路程/时间$ 求解。",
    "$$\n\\overline{A+B}=\\bar{A}\\bar{B}\n$$",
  ]) {
    assert.equal(normalizeMathMarkup(input), input);
  }
});

test("an unfinished formula is left alone while streaming", () => {
  assert.equal(normalizeMathMarkup("设 $x^2"), "设 $x^2");
});

// ---------------------------------------------------------------------------
// invariants
// ---------------------------------------------------------------------------

test("normalisation is idempotent", () => {
  for (const input of [
    "反演律 \\overline{A+B}=\\bar{A}\\bar{B} 必须熟练。",
    "价格 $100 起，另加 $20 运费。",
    "由此可得 \\(x+y\\) 成立。",
    "\\begin{aligned}\na &= b\n\\end{aligned}",
    "反演律 `\\bar{A}` 如上。",
  ]) {
    const once = normalizeMathMarkup(input);
    assert.equal(normalizeMathMarkup(once), once, input);
  }
});

test("routing agrees with what normalisation produces", () => {
  const shouldRender = [
    "反演律 \\overline{A+B}=\\bar{A}\\bar{B} 必须熟练。",
    "反演律 `\\overline{A+B}` 必须熟练。",
    "由此 $ x + y $ 成立。",
    "答案是 \\boxed{42}。",
  ];
  for (const input of shouldRender) {
    assert.equal(hasMarkdownMath(input), true, input);
    assert.notEqual(normalizeMathMarkup(input), input, input);
  }

  const shouldNot = [
    "价格是 $5 和 $10。",
    "把文件放到 C:\\Users\\frank\\Desktop 目录。",
    "运行 `npm run dev` 启动。",
  ];
  for (const input of shouldNot) {
    assert.equal(hasMarkdownMath(input), false, input);
  }
});

test("the routing predicates answer on their own terms", () => {
  assert.equal(hasInlineMathCandidate("设 $x=1$ 成立"), true);
  assert.equal(hasInlineMathCandidate("Tickets cost $5 and $10."), false);
  assert.equal(hasInlineMathCandidate("no dollars here"), false);

  assert.equal(hasBareLatexTrigger("用 \\overline{A} 表示"), true);
  assert.equal(hasBareLatexTrigger("C:\\Users\\frank"), false);
  assert.equal(hasBareLatexTrigger("no backslash"), false);
});
