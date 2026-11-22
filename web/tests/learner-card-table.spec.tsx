import { render, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MasteryQuestionCard } from "@/components/chat/home/MasteryQuestionCard";
import { initI18n } from "@/i18n/init";
import type { MasteryQuestion } from "@/lib/mastery-question";

initI18n("zh");

function masteryQuestion(): MasteryQuestion {
  return {
    questionId: "q1",
    prompt: "求平稳分布。",
    questionType: "multiple_choice",
    objectiveName: "马尔可夫链的转移矩阵、状态分类与极限分布",
    difficulty: "hard",
    attempt: 17,
    options: [
      { label: "A", body: "无穷多个" },
      { label: "B", body: "唯一" },
    ],
    allowFreeText: false,
  };
}

describe("learner-facing cards render the tutor's tables", () => {
  it("renders a GFM table in a mastery question stem", async () => {
    // The tutor wrote the transition matrix as a Markdown table. The stem
    // renderer is phrasing-only and only switched to the rich path for maths
    // or emphasis, so the whole table reached the learner as raw `|` rows.
    const prompt = [
      "一个三状态马尔可夫链（状态 1、2、3）的一期转移矩阵如下（行是「本期所处状态」，列是「下一期转到状态」）：",
      "| 本期\\下期 | 转到状态1 | 转到状态2 | 转到状态3 |",
      "|---|---|---|---|",
      "| 处于状态1 | 0.9 | 0.1 | 0 |",
      "| 处于状态2 | 0 | 0.9 | 0.1 |",
      "| 处于状态3 | 0 | 0 | 1 |",
      "关于这条链的状态分类与平稳分布，下列说法正确的是？",
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
      expect(container.querySelector("table")).not.toBeNull();
    });
    expect(container.querySelectorAll("th")).toHaveLength(4);
    expect(container.querySelectorAll("tbody tr")).toHaveLength(3);
    expect(container).toHaveTextContent("本期\\下期");
    expect(container).toHaveTextContent("处于状态2");
    expect(container).not.toHaveTextContent("|---|---|");
  });

  it("keeps the sentence under a table out of the table body", async () => {
    // No blank line after the last row: GFM would otherwise read the closing
    // question as one more single-cell row.
    const prompt = [
      "转移矩阵如下：",
      "| 本期\\下期 | 转到状态1 |",
      "|---|---|",
      "| 处于状态1 | 0.9 |",
      "下列说法正确的是？",
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
      expect(container.querySelector("table")).not.toBeNull();
    });
    expect(container.querySelectorAll("tbody tr")).toHaveLength(1);
    expect(container.querySelector("table")).not.toHaveTextContent(
      "下列说法正确的是？",
    );
  });
});
