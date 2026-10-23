import { describe, expect, it } from "vitest";

import { latestOpenMasteryQuestion } from "@/lib/mastery-question";
import type { StreamEvent } from "@/features/chat/model/protocol";

function posed(questionId: string): StreamEvent {
  return {
    type: "tool_result",
    metadata: {
      tool_metadata: {
        mastery_question: {
          question_id: questionId,
          prompt: "When do you write a workflow?",
          question_type: "short",
          allow_free_text: true,
          options: [],
        },
      },
    },
  } as StreamEvent;
}

describe("latestOpenMasteryQuestion", () => {
  it("closes the composer dock once the answer is in the conversation", () => {
    const messages = [
      { role: "assistant", events: [posed("q-1")] },
      {
        role: "user",
        content: "Use a workflow when the steps are enumerable.",
        requestSnapshot: {
          masteryAnswer: {
            question_id: "q-1",
            text: "Use a workflow when the steps are enumerable.",
          },
        },
      },
    ];

    expect(latestOpenMasteryQuestion(messages)).toBeNull();
  });

  it("keeps the dock when the answer never landed", () => {
    const messages = [
      { role: "assistant", events: [posed("q-1")] },
      {
        role: "user",
        failedSubmission: true,
        requestSnapshot: {
          masteryAnswer: { question_id: "q-1", text: "A guess." },
        },
      },
    ];

    expect(latestOpenMasteryQuestion(messages)?.questionId).toBe("q-1");
  });

  it("leaves a rejected answer in the conversation instead of reopening the dock", () => {
    const messages = [
      { role: "assistant", events: [posed("q-1")] },
      {
        role: "user",
        requestSnapshot: {
          masteryAnswer: { question_id: "q-1", text: "A guess." },
        },
      },
      {
        role: "assistant",
        events: [
          {
            type: "tool_result",
            metadata: {
              tool_metadata: {
                mastery_answer_rejected: { question_id: "q-1" },
              },
            },
          } as StreamEvent,
        ],
      },
    ];

    expect(latestOpenMasteryQuestion(messages)).toBeNull();
  });
});
