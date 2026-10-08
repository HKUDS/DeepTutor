import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";

initI18n("en");

/**
 * Smoke coverage for the state pool `StandaloneComposer` owns behind the
 * stateless `ChatComposer`: the empty-input guard, the happy-path send
 * payload, and the streaming lock (with its ask_user escape hatch). The
 * composer shell itself is stood in by a stub that records the props, so
 * these tests pin the pool's decisions, not the presentation.
 */
const harness = vi.hoisted(() => ({
  submitted: vi.fn(),
  composerProps: null as Record<string, unknown> | null,
}));

vi.mock("@/components/chat/home/ChatComposer", () => ({
  default: (props: Record<string, unknown>) => {
    harness.composerProps = props;
    return null;
  },
}));

vi.mock("@/features/knowledge/api/catalog", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/knowledge/api/catalog")
  >()),
  listKnowledgeBases: vi.fn(async () => []),
}));

vi.mock("@/lib/llm-options", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/llm-options")>()),
  listLLMOptions: vi.fn(async () => ({ options: [], active: null })),
}));

vi.mock("@/lib/subagents-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/subagents-api")>()),
  getSubagentSettings: vi.fn(async () => ({ consult_budget: 3 })),
}));

vi.mock("@/lib/attachment-limits", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/attachment-limits")>()),
  useAttachmentLimits: () => ({
    maxFileBytes: 50 * 1024 * 1024,
    maxTotalBytes: 200 * 1024 * 1024,
  }),
}));

vi.mock("@/components/notebook/NotebookRecordPicker", () => ({
  default: () => null,
}));
vi.mock("@/components/chat/HistorySessionPicker", () => ({
  default: () => null,
}));
vi.mock("@/components/chat/QuestionBankPicker", () => ({
  default: () => null,
}));
vi.mock("@/components/chat/PersonaPicker", () => ({ default: () => null }));
vi.mock("@/components/chat/MemoryPicker", () => ({ default: () => null }));
vi.mock("@/components/chat/BookReferencePicker", () => ({
  default: () => null,
}));
vi.mock("@/components/chat/home/CapabilityConfigCard", () => ({
  default: () => null,
}));
vi.mock("@/components/quiz/QuizConfigPanel", () => ({ default: () => null }));
vi.mock("@/components/visualize/VisualizeConfigPanel", () => ({
  default: () => null,
}));
vi.mock("@/components/research/ResearchConfigPanel", () => ({
  default: () => null,
}));

const { default: StandaloneComposer } = await import(
  "@/components/chat/home/StandaloneComposer"
);

type ComposerSend = (content: string) => Promise<void> | void;

async function mount(
  overrides: { isStreaming?: boolean; awaitingUserReply?: boolean } = {},
): Promise<{ onSend: ComposerSend }> {
  await act(async () => {
    render(
      <StandaloneComposer
        onSubmit={harness.submitted}
        onCancelStreaming={() => undefined}
        isStreaming={overrides.isStreaming ?? false}
        awaitingUserReply={overrides.awaitingUserReply ?? false}
        hasMessages={false}
        inputPlaceholder="Ask"
      />,
    );
  });
  return {
    onSend: harness.composerProps!.onSend as ComposerSend,
  };
}

const lastSubmission = () =>
  harness.submitted.mock.calls.at(-1)![0] as Record<string, unknown>;

describe("StandaloneComposer smoke", () => {
  beforeEach(() => {
    harness.submitted.mockClear();
    harness.composerProps = null;
  });

  it("refuses to send while the input is empty", async () => {
    const { onSend } = await mount();

    await act(async () => {
      await onSend("");
    });
    await act(async () => {
      await onSend("   ");
    });

    expect(harness.submitted).not.toHaveBeenCalled();
  });

  it("sends the text and consumes one-shot state after the send", async () => {
    const { onSend } = await mount();

    await act(async () => {
      await onSend("hello");
    });

    expect(harness.submitted).toHaveBeenCalledTimes(1);
    expect(lastSubmission()).toEqual(
      expect.objectContaining({
        content: "hello",
        attachments: [],
        knowledgeBases: [],
        notebookReferences: [],
        historyReferences: [],
        bookReferences: [],
        questionNotebookReferences: [],
        memoryReferences: [],
        persona: null,
        llmSelection: null,
        subagentBudget: null,
      }),
    );
    expect(lastSubmission().config).toMatchObject({
      _persistent_knowledge_bases: [],
    });

    await act(async () => {
      await onSend("");
    });
    expect(harness.submitted).toHaveBeenCalledTimes(1);
  });

  it("locks the send while a turn is streaming", async () => {
    const { onSend } = await mount({ isStreaming: true });

    await act(async () => {
      await onSend("hello");
    });

    expect(harness.submitted).not.toHaveBeenCalled();
  });

  it("lets an ask_user answer through the streaming lock", async () => {
    const { onSend } = await mount({
      isStreaming: true,
      awaitingUserReply: true,
    });

    await act(async () => {
      await onSend("the answer");
    });

    expect(harness.submitted).toHaveBeenCalledTimes(1);
    expect(lastSubmission()).toEqual(
      expect.objectContaining({ content: "the answer" }),
    );
  });
});
