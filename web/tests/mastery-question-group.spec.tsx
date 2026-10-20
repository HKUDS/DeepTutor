import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MasteryQuestionCard } from "@/components/chat/home/MasteryQuestionCard";
import { ChatMessageList } from "@/features/chat/messages";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { initI18n } from "@/i18n/init";
import type { UserReplyPayload } from "@/hooks/use-card-submission";
import {
  collectMasteryGrades,
  collectMasteryAnswerRejections,
  extractMasteryQuestion,
} from "@/lib/mastery-question";

initI18n("en");

const leaf = (id: string) => ({
  question_id: id,
  prompt: id === "part-a" ? "Select the matching description." : "Explain the distinction.",
  question_type: id === "part-a" ? "choice" : "short",
  objective: { id: `objective-${id}`, name: `Objective ${id}` },
  difficulty: "easy",
  attempt: 1,
  options: id === "part-a" ? [{ label: "A", body: "Matching description" }] : [],
  allow_free_text: true,
});

const group = {
  question_id: "group-1",
  question_type: "group",
  prompt: "Answer both parts.",
  questions: [leaf("part-a"), leaf("part-b")],
};

const event = (payload: Record<string, unknown>): StreamEvent => ({
  type: "tool_result", source: "mastery", stage: "responding", content: "",
  metadata: { tool_metadata: payload }, session_id: "session-1",
  turn_id: "turn-1", seq: 1, timestamp: 0,
});

const question = () => extractMasteryQuestion([event({ mastery_question: group })])!;

describe("grouped mastery assessment", () => {
  it("reopens a single clarification reply after a grading failure without losing its text", async () => {
    const user = userEvent.setup();
    const posed = { id: 1, role: "assistant" as const, content: "", parentMessageId: null,
      capability: "mastery_path", events: [event({ mastery_question: leaf("part-b") })] };
    const uncertain = event({ mastery_grade: { result: { question_id: "part-b",
      result: "ungraded", final: false, is_correct: null, learner_answer: "Unclear" } } });
    const conversation = (rejected: boolean) => <ChatMessageList messages={[posed,
      { id: 2, role: "assistant", content: "", parentMessageId: 1, capability: "mastery_path",
        events: [uncertain, ...(rejected ? [event({ mastery_answer_rejected: { question_id: "part-b" } })] : [])] }]}
      isStreaming={false} onCopyAssistantMessage={async () => undefined}
      onRegenerateMessage={() => undefined} onAnswerMasteryQuestion={() => true} />;
    const { rerender } = render(conversation(false));
    await user.clear(await screen.findByRole("textbox"));
    await user.type(screen.getByRole("textbox"), "Explicit revised explanation");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
    rerender(conversation(true));
    expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
    expect(screen.getByRole("textbox")).toHaveValue("Explicit revised explanation");
  });

  it("keeps uncertain leaves editable while final siblings stay locked", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => true);
    const grade = collectMasteryGrades([{ events: [event({ mastery_grade: { result: {
      question_id: "group-1", question_type: "group", complete: false, final: false,
      results: [
        { question_id: "part-a", result: "correct", final: true, is_correct: true, learner_answer: "A" },
        { question_id: "part-b", result: "ungraded", final: false, needs_clarification: true,
          is_correct: null, learner_answer: "Unclear", feedback: "Please explain the connection." },
      ],
    } } })] }]).get("group-1")!;
    render(<MasteryQuestionCard question={question()} grade={grade} answered={false}
      submittedAnswer="" onSubmit={onSubmit} />);
    expect(screen.getByRole("button", { name: /Matching description/ })).toBeDisabled();
    expect(screen.getByRole("textbox")).toBeEnabled();
    expect(screen.getByRole("textbox")).toHaveValue("Unclear");
    expect(screen.getByText("Please explain the connection.")).toBeInTheDocument();
    await user.clear(screen.getByRole("textbox"));
    await user.type(screen.getByRole("textbox"), "The connection is causal");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      answers: [{ questionId: "part-b", text: "The connection is causal" }],
    }));
  });

  it("normalizes two independent questions and drops private keys", () => {
    const normalized = question();
    expect(normalized).toMatchObject({
      questionId: "group-1", questionType: "group",
      questions: [{ questionId: "part-a" }, { questionId: "part-b" }],
    });
    const withPrivateKeys = extractMasteryQuestion([event({ mastery_question: {
      ...group, expected_answer: "private parent key",
      questions: group.questions.map((part) => ({ ...part, expected_answer: "private child key" })),
    } })]);
    expect(JSON.stringify(withPrivateKeys)).not.toContain("private");
  });

  it("clears old rejection on partial acknowledgement, but keeps a later rejection", () => {
    const rejected = event({ mastery_answer_rejected: { question_id: "group-1" } });
    const acknowledged = event({ mastery_grade: { result: { question_id: "group-1",
      question_type: "group", complete: false, is_correct: null, results: [
        { question_id: "part-a", is_correct: true, learner_answer: "A" },
      ] } } });
    expect(collectMasteryAnswerRejections([{ events: [rejected, acknowledged] }]).size).toBe(0);
    expect(collectMasteryAnswerRejections([{ events: [acknowledged, rejected] }]).has("group-1")).toBe(true);
  });

  it("rejects duplicate, nested, or incomplete group identities", () => {
    for (const questions of [[leaf("part-a")], [leaf("part-a"), leaf("part-a")],
      [leaf("part-a"), group]]) {
      expect(extractMasteryQuestion([event({ mastery_question: { ...group, questions } })])).toBeNull();
    }
  });

  it("allows one answer, or both together, with stable child IDs", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn(() => true);
    render(<MasteryQuestionCard question={question()} grade={null} answered={false}
      submittedAnswer="" onSubmit={onSubmit} />);
    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /Matching description/ }));
    expect(submit).toBeEnabled();
    await user.type(screen.getByRole("textbox"), "They have different roles");
    expect(submit).toBeEnabled();
    await user.click(submit);
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({
      text: "1. A\n2. They have different roles",
      answers: [
        { questionId: "part-a", text: "A" },
        { questionId: "part-b", text: "They have different roles" },
      ],
    });
  });

  it("keeps the remaining leaf editable on reload after a partial grade", async () => {
    const onSubmit = vi.fn(() => true);
    const grades = collectMasteryGrades([{ events: [event({ mastery_grade: {
      result: { question_id: "group-1", question_type: "group", complete: false,
        remaining_question_ids: ["part-b"], is_correct: null, result: "ungraded",
        results: [{ question_id: "part-a", is_correct: true, learner_answer: "A", explanation: "Confirmed first part." }] },
    } })] }]);
    expect(grades.get("group-1")).toMatchObject({ complete: false, isCorrect: null, remainingQuestionIds: ["part-b"] });
    const user = userEvent.setup();
    render(<MasteryQuestionCard question={question()} grade={grades.get("group-1")!}
      answered={false} submittedAnswer="" onSubmit={onSubmit} />);
    expect(screen.getByText("Correct")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Matching description/ })).toBeDisabled();
    expect(screen.getByRole("textbox")).toBeEnabled();
    await user.type(screen.getByRole("textbox"), "Remaining answer");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({ text: "2. Remaining answer",
      answers: [{ questionId: "part-b", text: "Remaining answer" }] });
  });

  it("restores a resumed partial group from the receipt in its own message without older history", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn(() => true);
    const resumedEvent = event({
      mastery_quiz: { status: "resumed", question_id: "group-1" },
      mastery_question: {
        ...group,
        questions: group.questions.map((part) => ({ ...part, expected_answer: "PRIVATE_QUESTION_KEY" })),
      },
      mastery_grade: { question_id: "group-1", complete: false, replayed: true,
        remaining_question_ids: ["part-b"], result: {
          question_id: "group-1", question_type: "group", is_correct: null, complete: false,
          remaining_question_ids: ["part-b"], results: [
            { question_id: "part-a", is_correct: true, learner_answer: "A", correct_label: "A",
              explanation: "First part already confirmed.", expected_answer: "PRIVATE_GRADE_KEY" },
          ],
        } },
    });
    // The re-presentation is the only loaded message: the original question
    // and earlier grade are intentionally absent from this history page.
    const messages = [{ id: 20, role: "assistant" as const, content: "", parentMessageId: null,
      capability: "mastery_path", events: [resumedEvent] }];
    const restored = collectMasteryGrades(messages);
    expect(restored.get("part-a")?.learnerAnswer).toBe("A");
    expect(restored.get("group-1")?.complete).toBe(false);
    expect(JSON.stringify([...restored.values()])).not.toContain("PRIVATE_");
    render(<ChatMessageList messages={messages} isStreaming={false}
      onCopyAssistantMessage={async () => undefined} onRegenerateMessage={() => undefined}
      onAnswerMasteryQuestion={onAnswer} />);
    expect(screen.getByRole("button", { name: /Matching description/ })).toBeDisabled();
    expect(screen.getByText("First part already confirmed.")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeEnabled();
    expect(document.body.textContent).not.toContain("PRIVATE_");
    await user.type(screen.getByRole("textbox"), "Answer after resuming");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(onAnswer).toHaveBeenCalledExactlyOnceWith({ questionId: "group-1", text: "2. Answer after resuming",
      answers: [{ questionId: "part-b", text: "Answer after resuming" }] });
  });

  it("releases the sending latch on partial acknowledgement and preserves unsent edits", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn<(payload: UserReplyPayload) => boolean>(() => true);
    const props = { question: question(), answered: false, submittedAnswer: "", onSubmit };
    const { rerender } = render(<MasteryQuestionCard {...props} grade={null} />);
    await user.click(screen.getByRole("button", { name: /Matching description/ }));
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(screen.getByRole("textbox")).toBeDisabled();
    rerender(<MasteryQuestionCard {...props} grade={null} rejectionKey="rejected-1" />);
    await user.type(screen.getByRole("textbox"), "Unsent draft");
    const partial = collectMasteryGrades([{ events: [event({ mastery_grade: { result: {
      question_id: "group-1", question_type: "group", complete: false, remaining_question_ids: ["part-b"],
      is_correct: null, results: [{ question_id: "part-a", is_correct: true, learner_answer: "A" }],
    } } })] }]).get("group-1")!;
    rerender(<MasteryQuestionCard {...props} grade={partial} />);
    expect(screen.getByRole("textbox")).toHaveValue("Unsent draft");
    expect(screen.getByRole("textbox")).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(onSubmit.mock.calls[1][0].answers).toEqual([{ questionId: "part-b", text: "Unsent draft" }]);
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  });

  it("actual message list leaves an incomplete group open and retains rejected remaining answers", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn(() => true);
    const posed = { id: 1, role: "assistant" as const, content: "", parentMessageId: null,
      capability: "mastery_path", events: [event({ mastery_question: group })] };
    const partial = event({ mastery_grade: { result: { question_id: "group-1", question_type: "group",
      complete: false, remaining_question_ids: ["part-b"], is_correct: null,
      results: [{ question_id: "part-a", is_correct: true, learner_answer: "A" }] } } });
    const conversation = (events: StreamEvent[]) => <ChatMessageList messages={[posed,
      { id: 2, role: "assistant", content: "", parentMessageId: 1, capability: "mastery_path", events }]}
      isStreaming={false} onCopyAssistantMessage={async () => undefined}
      onRegenerateMessage={() => undefined} onAnswerMasteryQuestion={onAnswer} />;
    const { rerender } = render(conversation([partial]));
    expect(screen.getByRole("textbox")).toBeEnabled();
    await user.type(screen.getByRole("textbox"), "Keep this after rejection");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    const rejection = { ...event({ mastery_answer_rejected: { question_id: "group-1" } }),
      turn_id: "retry-turn", seq: 2 };
    rerender(conversation([partial, rejection]));
    expect(screen.getByRole("textbox")).toHaveValue("Keep this after rejection");
    expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
  });

  it("retains both answers when delivery fails and allows a retry", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    render(<MasteryQuestionCard question={question()} grade={null} answered={false}
      submittedAnswer="" onSubmit={onSubmit} />);
    await user.click(screen.getByRole("button", { name: /Matching description/ }));
    await user.type(screen.getByRole("textbox"), "Retained answer");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(screen.getByRole("textbox")).toHaveValue("Retained answer");
    expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(onSubmit).toHaveBeenCalledTimes(2);
    expect(onSubmit.mock.calls[1]).toEqual(onSubmit.mock.calls[0]);
  });

  it("reconstructs independent mixed verdicts on reload, without an editable parent", () => {
    const grades = collectMasteryGrades([{ events: [event({ mastery_grade: {
      result: { question_id: "group-1", question_type: "group", is_correct: false,
        results: [
          { question_id: "part-a", is_correct: true, learner_answer: "A", correct_label: "A", explanation: "First part understood." },
          { question_id: "part-b", is_correct: false, learner_answer: "Incorrect distinction", explanation: "Second part needs correction." },
        ] },
    } })] }]);
    expect(grades.get("part-a")?.isCorrect).toBe(true);
    expect(grades.get("part-b")?.isCorrect).toBe(false);
    const { unmount } = render(<MasteryQuestionCard question={question()} grade={grades.get("group-1")!}
      answered submittedAnswer="" onSubmit={() => true} />);
    expect(screen.getByText("Correct")).toBeInTheDocument();
    expect(screen.getByText("Not quite")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit" })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    unmount();
    render(<MasteryQuestionCard question={question()} grade={grades.get("group-1")!}
      answered submittedAnswer="" onSubmit={() => true} />);
    expect(screen.getByText("First part understood.")).toBeInTheDocument();
    expect(screen.getByText("Second part needs correction.")).toBeInTheDocument();
  });

  it("skips the parent once, not each child", async () => {
    const user = userEvent.setup();
    const onSkip = vi.fn(() => true);
    render(<MasteryQuestionCard question={question()} grade={null} answered={false}
      submittedAnswer="" onSubmit={() => true} onSkip={onSkip} />);
    expect(screen.getAllByRole("button", { name: "Skip this one" })).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Skip this one" }));
    expect(onSkip).toHaveBeenCalledExactlyOnceWith("group-1");
  });

  it("keeps a failed source image from submitting the group", async () => {
    const user = userEvent.setup();
    const visualGroup = extractMasteryQuestion([event({ mastery_question: {
      ...group, questions: [group.questions[0], { ...group.questions[1], visual: {
        task: "identification", key_status: "verified", answer_cues: "none", sources: [
          { image_url: "/api/knowledge-bases/k/visual-assets/i", url: "/api/knowledge-bases/k/files/book.pdf", source_path: "book.pdf", page: 1 },
        ],
      } }],
    } })])!;
    render(<MasteryQuestionCard question={visualGroup} grade={null} answered={false}
      submittedAnswer="" onSubmit={() => true} />);
    await user.click(screen.getByRole("button", { name: /Matching description/ }));
    await user.type(screen.getByRole("textbox"), "Answer");
    expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
    fireEvent.error(screen.getByRole("img"));
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  });

  it("forwards both answer IDs through the actual message list callback", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn(() => true);
    render(<ChatMessageList messages={[{ id: 1, role: "assistant", content: "",
      parentMessageId: null, capability: "mastery_path", events: [event({ mastery_question: group })] }]}
      isStreaming={false} onCopyAssistantMessage={async () => undefined}
      onRegenerateMessage={() => undefined} onAnswerMasteryQuestion={onAnswer} />);
    await user.click(screen.getByRole("button", { name: /Matching description/ }));
    await user.type(screen.getByRole("textbox"), "Callback answer");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(onAnswer).toHaveBeenCalledExactlyOnceWith({
      questionId: "group-1", text: "1. A\n2. Callback answer",
      answers: [{ questionId: "part-a", text: "A" }, { questionId: "part-b", text: "Callback answer" }],
    });
  });

  it("challenges each graded leaf, never the aggregate parent", async () => {
    const user = userEvent.setup();
    const onChallenge = vi.fn(() => true);
    render(<MasteryQuestionCard question={question()} grade={{
      questionId: "group-1", isCorrect: false, learnerAnswer: "", correctLabel: "", correctBody: "", explanation: "",
      results: [
        { questionId: "part-a", isCorrect: true, learnerAnswer: "A", correctLabel: "A", correctBody: "", explanation: "Confirmed." },
        { questionId: "part-b", isCorrect: false, learnerAnswer: "Tentative", correctLabel: "", correctBody: "", explanation: "Evidence uncertain.", result: "ungraded" },
      ],
    }} answered submittedAnswer="" onSubmit={() => true} onChallenge={onChallenge} />);
    expect(screen.getByText("Correct")).toBeInTheDocument();
    expect(screen.getByText("Ungraded — mastery unchanged")).toBeInTheDocument();
    expect(screen.queryByText("Not quite")).toBeNull();
    const buttons = screen.getAllByRole("button", { name: "Review or challenge this assessment" });
    expect(buttons).toHaveLength(2);
    await user.click(buttons[0]);
    await user.click(buttons[1]);
    expect(onChallenge.mock.calls).toEqual([["part-a"], ["part-b"]]);
  });

  it("reopens an optimistically sent group for each real backend rejection event", async () => {
    const user = userEvent.setup();
    const onAnswer = vi.fn(() => true);
    const posed = { id: 1, role: "assistant" as const, content: "", parentMessageId: null,
      capability: "mastery_path", events: [event({ mastery_question: group })] };
    const rejection = (turnId: string): StreamEvent => ({
      ...event({ mastery_answer_rejected: { question_id: "group-1",
        message: "These answers could not be submitted. Please review or retry." } }),
      turn_id: turnId, metadata: { call_id: `mastery-grade-${turnId}-group-1`,
        tool_metadata: { mastery_answer_rejected: { question_id: "group-1",
          message: "These answers could not be submitted. Please review or retry." } } },
    });
    const conversation = (events: StreamEvent[]) => <ChatMessageList messages={[posed,
      { id: 2, role: "assistant", content: "", parentMessageId: 1,
        capability: "mastery_path", events }]}
      isStreaming={false} onCopyAssistantMessage={async () => undefined}
      onRegenerateMessage={() => undefined} onAnswerMasteryQuestion={onAnswer} />;
    const { rerender } = render(conversation([]));
    await user.click(screen.getByRole("button", { name: /Matching description/ }));
    await user.type(screen.getByRole("textbox"), "Preserved despite rejection");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();

    rerender(conversation([rejection("retry-1")]));
    expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
    expect(screen.getByText("These answers could not be submitted. Please review or retry.")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("Preserved despite rejection");
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();

    rerender(conversation([rejection("retry-1"), rejection("retry-2")]));
    expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(onAnswer).toHaveBeenCalledTimes(3);
    expect(onAnswer.mock.calls[2]).toEqual(onAnswer.mock.calls[0]);

    const success = event({ mastery_grade: { result: {
      question_id: "group-1", question_type: "group", is_correct: true,
      results: [
        { question_id: "part-a", is_correct: true, learner_answer: "A", explanation: "First confirmed." },
        { question_id: "part-b", is_correct: true, learner_answer: "Preserved despite rejection", explanation: "Second confirmed." },
      ],
    } } });
    rerender(conversation([rejection("retry-1"), rejection("retry-2"), success]));
    expect(screen.queryByRole("button", { name: "Submit" })).toBeNull();
    expect(screen.getAllByText("Correct")).toHaveLength(2);
    expect(screen.queryByText("These answers could not be submitted. Please review or retry.")).toBeNull();
  });
});
