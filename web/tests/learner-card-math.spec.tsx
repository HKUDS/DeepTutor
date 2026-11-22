import { render, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AskUserOptions } from "@/components/chat/home/AskUserOptions";
import { MasteryQuestionCard } from "@/components/chat/home/MasteryQuestionCard";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { initI18n } from "@/i18n/init";
import type { MasteryQuestion } from "@/lib/mastery-question";

initI18n("zh");

/**
 * The cards a learner answers on are written by the same tutor that writes the
 * prose above them, and on a maths or physics path that prose is LaTeX. Both
 * cards printed it verbatim — a Bellman-equation stem reached the reader as
 * `$G_t = R_{t+1} + \gamma G_{t+1}$`, and a bolded cue as `**听懂**`.
 */
function masteryQuestion(): MasteryQuestion {
  return {
    questionId: "q1",
    prompt: "已知 $G_t = R_{t+1} + \\gamma G_{t+1}$，关于 $V^\\pi$ 的方程是？",
    questionType: "multiple_choice",
    objectiveName: "Bellman",
    difficulty: "medium",
    attempt: 1,
    options: [
      { label: "A", body: "自举：$V^\\pi(s) = E_\\pi[R_{t+1}]$" },
      { label: "B", body: "蒙特卡洛采样" },
    ],
    allowFreeText: false,
  };
}

describe("learner-facing cards render the tutor's markup", () => {
  it("renders KaTeX in a mastery question stem, its options and its verdict", async () => {
    const { container } = render(
      <MasteryQuestionCard
        question={masteryQuestion()}
        grade={{
          questionId: "q1",
          isCorrect: true,
          learnerAnswer: "A",
          correctLabel: "A",
          correctBody: "",
          explanation: "代入可得 $V^\\pi(s)$。",
        }}
        answered
        submittedAnswer="A"
        onSubmit={() => undefined}
      />,
    );

    await waitFor(() => {
      expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(
        4,
      );
    });
    expect(container).not.toHaveTextContent("$V^\\pi$");
  });

  it("renders a matrix written as a bare LaTeX environment on an answer card", async () => {
    // The tutor writes the state-transition matrix with no delimiters around
    // it; the card used to show `\begin{pmatrix} …` as source.
    const matrix = String.raw`\begin{pmatrix} 0.5 & 0.5 & 0 & 0\\ 0.5 & 0.5 & 0 & 0\\ 0.2 & 0 & 0.4 & 0.4\\ 0 & 0.3 & 0.3 & 0.4 \end{pmatrix}`;
    const { container } = render(
      <MasteryQuestionCard
        question={{
          ...masteryQuestion(),
          prompt: `单步转移矩阵如下：\n\n${matrix}\n\n长期来看处在状态 1 的时间比例是多少？`,
        }}
        grade={null}
        answered={false}
        submittedAnswer=""
        onSubmit={() => undefined}
      />,
    );

    await waitFor(() => {
      expect(
        container.querySelectorAll(".katex").length,
      ).toBeGreaterThanOrEqual(1);
    });
    expect(container.querySelector(".katex-error")).toBeNull();
    // KaTeX renders an environment as a MathML table, not a run of text.
    expect(container.querySelector(".katex mtable")).not.toBeNull();
  });

  it("renders a display matrix whose $$ fences hug the environment", async () => {
    // Exactly what a mastery question carried: remark-math only reads a
    // multi-line display block with each `$$` on its own line, so this used
    // to reach KaTeX as inline maths and fail on its first `&`.
    const prompt = [
      "某四状态时齐马尔可夫链的单步转移矩阵如下：",
      "",
      "$$P=\\begin{pmatrix}",
      "0.5 & 0.5 & 0 & 0\\\\",
      "0.5 & 0.5 & 0 & 0\\\\",
      "0.2 & 0 & 0.4 & 0.4\\\\",
      "0 & 0.3 & 0.3 & 0.4",
      "\\end{pmatrix}$$",
      "",
      "问：长期来看，处在状态 1 的时间比例是多少？",
    ].join("\n");
    const { container } = render(
      <MasteryQuestionCard
        question={{ ...masteryQuestion(), prompt }}
        grade={null}
        answered={false}
        submittedAnswer=""
        onSubmit={() => undefined}
      />,
    );

    await waitFor(() => {
      expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(
        1,
      );
    });
    expect(container.querySelector(".katex-error")).toBeNull();
    expect(container.querySelector(".katex mtable")).not.toBeNull();
  });

  it("renders math and emphasis on an ask_user card", async () => {
    const { container } = render(
      <AskUserOptions
        data={{
          resolved: false,
          answers: [],
          payload: {
            intro: "先确认一件事：**听懂**了吗？",
            questions: [
              {
                id: "goal",
                prompt: "$e^{i\\pi} + 1 = 0$ 说明了什么？",
                header: "Goal",
                multi_select: false,
                allow_free_text: false,
                placeholder: null,
                options: [
                  { label: "$\\pi$ 与 $e$ 的关系", description: null },
                  { label: "别的", description: null },
                ],
              },
            ],
          },
        }}
        onSubmit={() => undefined}
      />,
    );

    await waitFor(() => {
      expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(
        2,
      );
    });
    expect(container).not.toHaveTextContent("**听懂**");
  });

  it("renders math in a trace bubble", async () => {
    const { container } = render(
      <MarkdownRenderer
        content="特征方程 $r^2 + 2r + 5 = 0$，判别式 $\\Delta = -16 < 0$。"
        variant="trace"
      />,
    );

    await waitFor(() => {
      expect(container.querySelectorAll(".katex")).toHaveLength(2);
    });
    expect(container).not.toHaveTextContent("$r^2 + 2r + 5 = 0$");
  });
});
