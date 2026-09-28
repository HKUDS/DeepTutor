import { render, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import QuizBlock from "@/app/(workspace)/learning/books/components/blocks/QuizBlock";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { initI18n } from "@/i18n/init";
import type { Block } from "@/lib/book-types";

initI18n("zh");

describe("math Markdown rendering", () => {
  it("renders the plain inline formulas from the reported chat response with KaTeX", async () => {
    const { container } = render(
      <MarkdownRenderer
        content="假设有一个函数 $f(x)$，在 $x=2$ 这个点上，函数值趋近 $5$。"
        variant="prose"
      />,
    );

    await waitFor(() => {
      expect(container.querySelectorAll(".katex")).toHaveLength(3);
    });
    expect(container).not.toHaveTextContent("$f(x)$");
    expect(container).not.toHaveTextContent("$x=2$");
  });

  it("renders the formulas a model wrote without $ delimiters", async () => {
    const { container } = render(
      <MarkdownRenderer
        content={"反演律 \\overline{A+B}=\\bar{A}\\bar{B} 必须熟练。"}
        variant="prose"
      />,
    );

    await waitFor(() => {
      expect(container.querySelectorAll(".katex")).toHaveLength(1);
    });
    // KaTeX keeps the source in a MathML <annotation>, so assert on what the
    // reader actually sees rather than on the element's text content.
    expect(container.querySelector(".katex-html")?.textContent).not.toContain(
      "\\overline",
    );
  });

  it("renders a formula the model put in a code span", async () => {
    const { container } = render(
      <MarkdownRenderer
        content={"反演律 `\\overline{A+B}=\\bar{A}\\bar{B}` 必须熟练。"}
        variant="prose"
      />,
    );

    await waitFor(() => {
      expect(container.querySelectorAll(".katex")).toHaveLength(1);
    });
    expect(container.querySelector("code")).toBeNull();
  });

  it("keeps prices as prices in a message that also renders maths", async () => {
    const { container } = render(
      <MarkdownRenderer
        content={"设 $x=1$。门票 $5 和 $10，共 $15。"}
        variant="prose"
      />,
    );

    await waitFor(() => {
      expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(
        1,
      );
    });
    expect(container).toHaveTextContent("门票 $5 和 $10，共 $15。");
  });

  it("renders generated quiz stems and option formulas with KaTeX", async () => {
    const block: Block = {
      id: "math-quiz",
      type: "quiz",
      status: "ready",
      title: "",
      params: {},
      payload: {
        questions: [
          {
            question_id: "q1",
            question: "若 $f(x)=x^2$，则 $f(2)$ 等于多少？",
            question_type: "multiple_choice",
            options: { A: "$2$", B: "$4$" },
            correct_answer: "B",
            explanation: "代入可得 $f(2)=2^2=4$。",
          },
        ],
      },
      source_anchors: [],
      metadata: {},
      error: "",
      created_at: 0,
      updated_at: 0,
    };

    const { container } = render(<QuizBlock block={block} />);

    await waitFor(() => {
      expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(
        4,
      );
    });
    expect(container).not.toHaveTextContent("$f(x)=x^2$");
    expect(container).not.toHaveTextContent("$4$");
  });
});
