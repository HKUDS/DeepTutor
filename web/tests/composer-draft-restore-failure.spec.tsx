import { StrictMode, useRef } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MessageSquare } from "lucide-react";

import ChatComposer from "@/components/chat/home/ChatComposer";
import type { CapabilityDef } from "@/features/capabilities/presentation";
import type { WorkspaceDraft } from "@/lib/workspace-drafts";

const drafts = vi.hoisted(() => ({
  read: vi.fn<() => Promise<unknown>>(),
  save: vi.fn<(draft: WorkspaceDraft) => Promise<void>>(),
}));
const draftLocation = vi.hoisted(() => ({
  current: { workspaceId: "ws_test", pathname: "/chat" },
}));

vi.mock("@/lib/workspace-drafts", () => ({
  currentWorkspaceDraftLocation: () => draftLocation.current,
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
  draftLocation.current = { workspaceId: "ws_test", pathname: "/chat" };
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
  }, "ws_test", "/chat");
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
  }, "ws_test", "/chat");
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
  }, "ws_test", "/chat");
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
  }, "ws_test", "/chat");
});

it("autosaves typed text after a short pause", async () => {
  vi.useFakeTimers();
  try {
    drafts.read.mockResolvedValue(undefined);
    drafts.save.mockResolvedValue(undefined);
    render(<Harness />);
    await act(async () => {});

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "half-written question" },
    });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(drafts.save).toHaveBeenCalledWith({
      text: "half-written question",
      attachments: [],
    }, "ws_test", "/chat");
  } finally {
    vi.useRealTimers();
  }
});

it("flushes a pending draft when the composer unmounts", async () => {
  drafts.read.mockResolvedValue(undefined);
  drafts.save.mockResolvedValue(undefined);
  const { unmount } = render(<Harness />);
  await act(async () => {});

  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "not sent yet" },
  });
  unmount();
  await act(async () => {});

  expect(drafts.save).toHaveBeenCalledWith({
    text: "not sent yet",
    attachments: [],
  }, "ws_test", "/chat");
});

it("does not overwrite a stored draft when an empty composer unmounts", async () => {
  drafts.read.mockResolvedValue({ text: "stored draft", attachments: [] });
  drafts.save.mockResolvedValue(undefined);
  const { unmount } = render(<Harness />);
  await act(async () => {});

  unmount();
  await act(async () => {});

  expect(drafts.save).not.toHaveBeenCalled();
});

it("saves under the route where the text was typed", async () => {
  draftLocation.current = { workspaceId: "ws_test", pathname: "/chat/one" };
  drafts.read.mockResolvedValue(undefined);
  drafts.save.mockResolvedValue(undefined);
  const { unmount } = render(<Harness />);
  await act(async () => {});

  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "route-bound draft" },
  });
  draftLocation.current = { workspaceId: "ws_test", pathname: "/settings" };
  unmount();
  await act(async () => {});

  expect(drafts.save).toHaveBeenCalledWith({
    text: "route-bound draft",
    attachments: [],
  }, "ws_test", "/chat/one");
});

it("merges text typed before the stored draft finishes loading", async () => {
  let resolveRead!: (value: unknown) => void;
  drafts.read.mockReturnValue(new Promise((resolve) => {
    resolveRead = resolve;
  }));
  drafts.save.mockResolvedValue(undefined);
  render(<Harness />);

  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "typed early" },
  });
  expect(drafts.save).not.toHaveBeenCalled();

  await act(async () => {
    resolveRead({ text: "stored draft", attachments: [] });
  });

  expect(screen.getByRole("textbox")).toHaveValue("stored draft\ntyped early");
});

it("does not duplicate the stored draft when autosave and a workspace switch both merge", async () => {
  vi.useFakeTimers();
  try {
    drafts.read
      .mockRejectedValueOnce(new Error("indexeddb unavailable"))
      .mockResolvedValueOnce({ text: "stored draft", attachments: [] });
    drafts.save.mockResolvedValue(undefined);
    render(<Harness />);
    await act(async () => {});

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "typed after failure" },
    });
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(drafts.save).toHaveBeenLastCalledWith({
      text: "stored draft\ntyped after failure",
      attachments: [],
    }, "ws_test", "/chat");

    const pending = switchWorkspace();
    await expect(Promise.all(pending)).resolves.toBeDefined();
    expect(drafts.save).toHaveBeenCalledTimes(2);
    expect(drafts.save).toHaveBeenLastCalledWith({
      text: "stored draft\ntyped after failure",
      attachments: [],
    }, "ws_test", "/chat");
  } finally {
    vi.useRealTimers();
  }
});

it("clears the sent draft under the route it was typed on", async () => {
  draftLocation.current = { workspaceId: "ws_test", pathname: "/chat/one" };
  drafts.read.mockResolvedValue(undefined);
  drafts.save.mockResolvedValue(undefined);
  const onSend = vi.fn();
  render(<Harness onSend={onSend} />);
  await act(async () => {});

  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "send me" } });
  fireEvent.keyDown(input, { key: "Enter" });

  await act(async () => {});
  expect(onSend).toHaveBeenCalledWith("send me");
  expect(drafts.save).toHaveBeenCalledWith({
    text: "",
    attachments: [],
  }, "ws_test", "/chat/one");
});

// Independent review regressions: these should pass before merge.
it("review: preserves typing when navigation precedes draft read", async () => {
  let resolveRead!: (value: unknown) => void;
  drafts.read.mockReturnValue(new Promise(resolve => { resolveRead = resolve; }));
  drafts.save.mockResolvedValue(undefined);
  const { unmount } = render(<Harness />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "new input" } });
  unmount();
  await act(async () => { resolveRead({text:"stored", attachments:[]}); });
  expect(drafts.save).toHaveBeenCalledWith({text:"stored\nnew input", attachments:[]}, "ws_test", "/chat");
});
it("review: restores the draft under StrictMode", async () => {
  drafts.read.mockResolvedValue({text:"stored", attachments:[]});
  drafts.save.mockResolvedValue(undefined);
  render(<StrictMode><Harness /></StrictMode>);
  await act(async () => {});
  expect(screen.getByRole("textbox")).toHaveValue("stored");
});


it("serializes send cleanup after an in-flight autosave", async () => {
  vi.useFakeTimers();
  try {
    let finishSave!: () => void;
    drafts.read.mockResolvedValue(undefined);
    drafts.save.mockImplementationOnce(() => new Promise<void>(resolve => { finishSave = resolve; })).mockResolvedValue(undefined);
    render(<Harness />);
    await act(async () => {});
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "send me" } });
    await act(async () => { vi.advanceTimersByTime(500); });
    expect(drafts.save).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(drafts.save).toHaveBeenCalledTimes(1);
    await act(async () => { finishSave(); });
    expect(drafts.save).toHaveBeenLastCalledWith({text: "", attachments: []}, "ws_test", "/chat");
  } finally { vi.useRealTimers(); }
});

it("serializes workspace-switch persistence after autosave", async () => {
  vi.useFakeTimers();
  let finishSave!: () => void;
  let stored = "";
  try {
    drafts.read.mockResolvedValue(undefined);
    drafts.save.mockImplementationOnce((draft) => new Promise<void>(resolve => {
      finishSave = () => {stored = draft.text; resolve();};
    })).mockImplementation(async (draft) => {stored = draft.text;});
    const { unmount } = render(<Harness />);
    await act(async () => {});
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "old text" } });
    await act(async () => { vi.advanceTimersByTime(500); });
    expect(drafts.save).toHaveBeenCalledTimes(1);
    fireEvent.change(input, { target: { value: "new text" } });
    const pending = switchWorkspace();
    await act(async () => { await Promise.resolve(); });
    // Both writes must run in order; an older autosave may not replace the switch's latest draft.
    await act(async () => {finishSave(); await Promise.all(pending);});
    expect(stored).toBe("new text");
    unmount();
  } finally {vi.useRealTimers();}
});

it("does not resurrect the source after a workspace draft transfer", async () => {
  vi.useFakeTimers();
  let stored = "";
  try {
    drafts.read.mockResolvedValue(undefined);
    drafts.save.mockImplementation(async (draft) => {stored = draft.text;});
    const { unmount } = render(<Harness />);
    await act(async () => {});
    fireEvent.change(screen.getByRole("textbox"), {target: {value: "move this"}});
    await act(async () => {await Promise.all(switchWorkspace());});
    expect(stored).toBe("move this");
    // useWorkspaceBinding's beforeNavigate transfers the saved source and then deletes it.
    stored = "";
    unmount();
    await act(async () => {});
    expect(stored).toBe("");
  } finally {vi.useRealTimers();}
});

it("keeps input typed while a workspace-switch save is pending", async () => {
  vi.useFakeTimers();
  let finishSave!: () => void;
  let stored = "";
  try {
    drafts.read.mockResolvedValue(undefined);
    drafts.save.mockImplementationOnce((draft) => new Promise<void>(resolve => {
      finishSave = () => {stored = draft.text; resolve();};
    })).mockImplementation(async (draft) => {stored = draft.text;});
    const { unmount } = render(<Harness />);
    await act(async () => {});
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "before switch" } });
    const pending = switchWorkspace();
    await act(async () => {});
    fireEvent.change(input, { target: { value: "typed during save" } });
    await act(async () => {finishSave(); await Promise.all(pending);});
    unmount();
    await act(async () => {});
    expect(stored).toBe("typed during save");
  } finally {vi.useRealTimers();}
});
