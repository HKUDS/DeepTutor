import { useRef } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MessageSquare } from "lucide-react";

import ChatComposer from "@/components/chat/home/ChatComposer";
import type { CapabilityDef } from "@/features/capabilities/presentation";

const drafts = vi.hoisted(() => ({
  read: vi.fn<() => Promise<unknown>>(),
  save: vi.fn<() => Promise<void>>(),
}));

vi.mock("@/lib/workspace-drafts", () => ({
  readWorkspaceDraft: drafts.read,
  saveWorkspaceDraft: drafts.save,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const activeCap: CapabilityDef = {
  value: "",
  label: "Chat",
  description: "Flexible conversation with any tool",
  icon: MessageSquare,
  allowedTools: [],
};

// Drop queued once-mocks so a test whose re-read never happens (e.g. on the
// pre-fix code, where the switch chain rejects first) cannot leak its
// responses into the next test.
beforeEach(() => {
  drafts.read.mockReset();
  drafts.save.mockReset();
});

function Harness({ onSend = () => {} }: { onSend?: (content: string) => void }) {
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
      spaceMenuOpen={false}
      hasMessages={false}
      attachments={[]}
      attachmentError={null}
      activeCap={activeCap}
      knowledgeBases={[]}
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
      selectedKnowledgeBases={[]}
      isStreaming={false}
      isVisualizeMode={false}
      capabilityNeedsConfig={false}
      capabilityConfigConfirmed={false}
      onRequestConfigConfirm={() => {}}
      capabilities={[activeCap]}
      onSetCapMenuOpen={() => {}}
      onSetSpaceMenuOpen={() => {}}
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
      onSend={onSend}
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

function switchWorkspace(): Promise<void>[] {
  const pending: Promise<void>[] = [];
  act(() => {
    window.dispatchEvent(
      new CustomEvent<Promise<void>[]>("deeptutor:before-workspace-switch", {
        detail: pending,
      }),
    );
  });
  return pending;
}

it("keeps the workspace switch usable when restore failed and nothing new was typed", async () => {
  drafts.read.mockRejectedValue(new Error("indexeddb unavailable"));
  drafts.save.mockResolvedValue(undefined);
  render(<Harness />);

  const pending = switchWorkspace();

  await expect(Promise.all(pending)).resolves.toBeDefined();
  expect(drafts.save).not.toHaveBeenCalled();
});

it("saves newly typed text merged with the stored draft when switching after a failed restore", async () => {
  drafts.read
    .mockRejectedValueOnce(new Error("indexeddb unavailable"))
    .mockResolvedValueOnce({ text: "stored draft", attachments: [] });
  drafts.save.mockResolvedValue(undefined);
  render(<Harness />);
  await act(async () => {});

  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "typed after failure" },
  });
  const pending = switchWorkspace();

  await expect(Promise.all(pending)).resolves.toBeDefined();
  expect(drafts.save).toHaveBeenCalledTimes(1);
  expect(drafts.save).toHaveBeenCalledWith({
    text: "stored draft\ntyped after failure",
    attachments: [],
  });
});

it("keeps typed text on a retried switch after the first merge save failed", async () => {
  drafts.read
    .mockRejectedValueOnce(new Error("indexeddb unavailable"))
    .mockResolvedValueOnce(undefined);
  drafts.save
    .mockRejectedValueOnce(new Error("QuotaExceededError"))
    .mockResolvedValue(undefined);
  render(<Harness />);
  await act(async () => {});

  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "typed after failure" },
  });
  let pending = switchWorkspace();
  await expect(Promise.all(pending)).rejects.toBeDefined();

  pending = switchWorkspace();
  await expect(Promise.all(pending)).resolves.toBeDefined();
  expect(drafts.save).toHaveBeenCalledTimes(2);
  expect(drafts.save).toHaveBeenLastCalledWith({
    text: "typed after failure",
    attachments: [],
  });
});

it("keeps typed text when the stored draft has attachments but no text", async () => {
  const storedAttachments = [
    { filename: "notes.pdf", base64: "Zm9v", mimeType: "application/pdf" },
  ];
  drafts.read
    .mockRejectedValueOnce(new Error("indexeddb unavailable"))
    .mockResolvedValueOnce({ text: "", attachments: storedAttachments });
  drafts.save.mockResolvedValue(undefined);
  render(<Harness />);
  await act(async () => {});

  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "typed after failure" },
  });
  const pending = switchWorkspace();

  await expect(Promise.all(pending)).resolves.toBeDefined();
  expect(drafts.save).toHaveBeenCalledTimes(1);
  expect(drafts.save).toHaveBeenCalledWith({
    text: "typed after failure",
    attachments: storedAttachments,
  });
});

it("rejects the switch when a re-read of the stored draft still fails after new input", async () => {
  drafts.read.mockRejectedValue(new Error("indexeddb unavailable"));
  drafts.save.mockResolvedValue(undefined);
  render(<Harness />);
  await act(async () => {});

  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "typed after failure" },
  });
  const pending = switchWorkspace();

  await expect(Promise.all(pending)).rejects.toBeDefined();
  expect(drafts.save).not.toHaveBeenCalled();
});

it("does not clear the stored draft when the user sends text after a failed restore", async () => {
  drafts.read.mockRejectedValue(new Error("indexeddb unavailable"));
  drafts.save.mockResolvedValue(undefined);
  const onSend = vi.fn();
  render(<Harness onSend={onSend} />);
  await act(async () => {});

  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "typed after failed restore" } });
  fireEvent.keyDown(input, { key: "Enter" });

  expect(onSend).toHaveBeenCalledWith("typed after failed restore");
  expect(drafts.save).not.toHaveBeenCalled();
});

it("still saves the composer content on workspace switch after a successful restore", async () => {
  drafts.read.mockResolvedValue(undefined);
  drafts.save.mockResolvedValue(undefined);
  render(<Harness />);

  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "saved on switch" },
  });
  const pending = switchWorkspace();

  await expect(Promise.all(pending)).resolves.toBeDefined();
  expect(drafts.save).toHaveBeenCalledWith({
    text: "saved on switch",
    attachments: [],
  });
});
