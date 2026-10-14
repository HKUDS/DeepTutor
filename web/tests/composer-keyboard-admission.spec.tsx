import { createRef, type ComponentProps } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MessageSquare } from "lucide-react";

import ChatComposer from "@/components/chat/home/ChatComposer";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/lib/workspace-drafts", () => ({
  readWorkspaceDraft: async () => null,
  saveWorkspaceDraft: async () => undefined,
}));

function composer(overrides: Partial<ComponentProps<typeof ChatComposer>> = {}) {
  const onSend = vi.fn();
  const onRequestConfigConfirm = vi.fn();
  const noop = () => undefined;
  const props: ComponentProps<typeof ChatComposer> = {
    composerRef: createRef(), capMenuRef: createRef(), capBtnRef: createRef(),
    spaceMenuRef: createRef(), spaceBtnRef: createRef(), dragCounter: { current: 0 },
    dragging: false, capMenuOpen: false, spaceMenuOpen: false, hasMessages: true,
    attachments: [], attachmentError: null,
    activeCap: { value: "", label: "Chat", description: "Chat", icon: MessageSquare,
      allowedTools: [] },
    knowledgeBases: [], llmOptions: [], activeLLMDefault: null, llmSelection: null,
    llmOptionsLoading: false, llmOptionsError: false,
    selectedNotebookRecords: [], selectedBookReferences: [], selectedHistorySessions: [],
    selectedAgentSessions: [], selectedQuestionEntries: [], notebookReferenceGroups: [],
    selectedPersona: null, selectedMemoryFiles: [], selectedKnowledgeBases: [],
    isStreaming: false, isVisualizeMode: false, capabilityNeedsConfig: false,
    capabilityConfigConfirmed: false, onRequestConfigConfirm, capabilities: [],
    onSetCapMenuOpen: noop, onSetSpaceMenuOpen: noop, onToggleKB: noop,
    onSelectLLM: noop, onSelectNotebookPicker: noop, onSelectBookPicker: noop,
    onSelectHistoryPicker: noop, onSelectAgentsPicker: noop, onSelectQuestionBankPicker: noop,
    onSelectPersonaPicker: noop, onSelectMemoryPicker: noop, onClearPersona: noop,
    onToggleMemoryFile: noop, onSend, onRemoveAttachment: noop, onRemoveHistory: noop,
    onRemoveAgent: noop, onRemoveBookReference: noop, onRemoveNotebook: noop,
    onRemoveQuestion: noop, onDragEnter: noop, onDragLeave: noop, onDragOver: noop,
    onDrop: noop, onPaste: noop, onAddFiles: noop, onSelectCapability: noop,
    onCancelStreaming: noop,
    ...overrides,
  };
  render(<ChatComposer {...props} />);
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "Explain limits" } });
  return { input, onSend, onRequestConfigConfirm };
}

it("opens the required configuration on Enter and preserves the unsent draft", async () => {
  const { input, onSend, onRequestConfigConfirm } = composer({ capabilityNeedsConfig: true });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(onRequestConfigConfirm).toHaveBeenCalledOnce());
  expect(onSend).not.toHaveBeenCalled();
  expect(input).toHaveValue("Explain limits");
});

it("sends an answer with Enter while the streaming turn awaits the user", () => {
  const { input, onSend } = composer({ isStreaming: true, awaitingUserReply: true });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onSend).toHaveBeenCalledExactlyOnceWith("Explain limits");
  expect(input).toHaveValue("");
});

it("preserves text while an ordinary turn is streaming", () => {
  const { input, onSend } = composer({ isStreaming: true });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onSend).not.toHaveBeenCalled();
  expect(input).toHaveValue("Explain limits");
});

it("sends confirmed configuration and keeps Shift Enter available", () => {
  const { input, onSend } = composer({ capabilityNeedsConfig: true, capabilityConfigConfirmed: true });
  fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
  expect(onSend).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onSend).toHaveBeenCalledExactlyOnceWith("Explain limits");
});
