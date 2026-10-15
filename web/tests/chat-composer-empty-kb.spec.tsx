import { useRef, useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Database, MessageSquare } from "lucide-react";

import ChatComposer from "@/components/chat/home/ChatComposer";
import type { CapabilityDef } from "@/features/capabilities/presentation";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/lib/workspace-drafts", () => ({
  readWorkspaceDraft: vi.fn().mockResolvedValue(null),
  saveWorkspaceDraft: vi.fn().mockResolvedValue(undefined),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const activeCap: CapabilityDef = {
  value: "",
  label: "Chat",
  description: "Flexible conversation with any tool",
  icon: MessageSquare,
  allowedTools: [],
};

function Harness({
  knowledgeBases = [],
  selectedKnowledgeBases = [],
}: {
  knowledgeBases?: { name: string }[];
  selectedKnowledgeBases?: string[];
}) {
  const [spaceOpen, setSpaceOpen] = useState(false);
  const composerRef = useRef<HTMLDivElement>(null);
  const capMenuRef = useRef<HTMLDivElement>(null);
  const capBtnRef = useRef<HTMLButtonElement>(null);
  const spaceMenuRef = useRef<HTMLDivElement>(null);
  const spaceBtnRef = useRef<HTMLButtonElement>(null);
  const dragCounter = useRef(0);

  return (
    <ChatComposer
      composerRef={composerRef}
      capMenuRef={capMenuRef}
      capBtnRef={capBtnRef}
      spaceMenuRef={spaceMenuRef}
      spaceBtnRef={spaceBtnRef}
      dragCounter={dragCounter}
      dragging={false}
      capMenuOpen={false}
      spaceMenuOpen={spaceOpen}
      hasMessages={false}
      attachments={[]}
      attachmentError={null}
      activeCap={activeCap}
      knowledgeBases={knowledgeBases}
      llmOptions={[]}
      activeLLMDefault={null}
      llmSelection={null}
      llmOptionsLoading={false}
      llmOptionsError={false}
      selectedNotebookRecords={[]}
      selectedBookReferences={[]}
      selectedHistorySessions={[]}
      selectedAgentSessions={[]}
      selectedQuestionEntries={[]}
      notebookReferenceGroups={[]}
      selectedPersona={null}
      selectedMemoryFiles={[]}
      selectedKnowledgeBases={selectedKnowledgeBases}
      isStreaming={false}
      isVisualizeMode={false}
      capabilityNeedsConfig={false}
      capabilityConfigConfirmed={false}
      onRequestConfigConfirm={() => {}}
      capabilities={[activeCap]}
      onSetCapMenuOpen={() => {}}
      onSetSpaceMenuOpen={setSpaceOpen}
      onToggleKB={() => {}}
      onSelectLLM={() => {}}
      onSelectNotebookPicker={() => {}}
      onSelectBookPicker={() => {}}
      onSelectHistoryPicker={() => {}}
      onSelectAgentsPicker={() => {}}
      onSelectQuestionBankPicker={() => {}}
      onSelectPersonaPicker={() => {}}
      onSelectMemoryPicker={() => {}}
      onClearPersona={() => {}}
      onToggleMemoryFile={() => {}}
      onSend={() => {}}
      onRemoveAttachment={() => {}}
      onRemoveHistory={() => {}}
      onRemoveAgent={() => {}}
      onRemoveBookReference={() => {}}
      onRemoveNotebook={() => {}}
      onRemoveQuestion={() => {}}
      onDragEnter={() => {}}
      onDragLeave={() => {}}
      onDragOver={() => {}}
      onDrop={() => {}}
      onPaste={() => {}}
      onAddFiles={() => {}}
      onSelectCapability={() => {}}
      onCancelStreaming={() => {}}
    />
  );
}

it("keeps knowledge base entry available with 'No KB' summary when knowledge bases are empty", () => {
  render(<Harness knowledgeBases={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Resources" }));

  const kbButton = screen.getByRole("button", { name: /Knowledge.*No KB/ });
  expect(kbButton).toBeInTheDocument();

  fireEvent.click(kbButton);
  expect(screen.getByText("No knowledge bases available")).toBeInTheDocument();
  expect(screen.getByText("Create your first knowledge base")).toBeInTheDocument();
});

it("displays 'Default' summary and lists knowledge bases when configured", () => {
  render(<Harness knowledgeBases={[{ name: "Chemistry" }]} />);
  fireEvent.click(screen.getByRole("button", { name: "Resources" }));

  const kbButton = screen.getByRole("button", { name: /Knowledge.*Default/ });
  expect(kbButton).toBeInTheDocument();

  fireEvent.click(kbButton);
  expect(screen.getByText("Chemistry")).toBeInTheDocument();
});
