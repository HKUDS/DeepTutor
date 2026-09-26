import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";
import type { ResourceSelection } from "@/features/chat/ChatStateAdapter";
import type { ComposerResourceCatalog } from "@/hooks/useComposerResources";

initI18n("en");

const captured = vi.hoisted(() => ({
  props: null as {
    resourceCatalog?: ComposerResourceCatalog;
    resourceSelection?: ResourceSelection;
    onResourceSelectionChange?: (selection: ResourceSelection) => void;
  } | null,
  setResourceSelection: vi.fn(),
  catalog: {
    skills: [{ id: "skill-1", name: "Tutor" }],
    mcp: [{ id: "mcp-1", name: "Search" }],
  },
  selection: { skills: ["skill-1"], mcp: [] as string[] },
}));

vi.mock("@/features/chat/ChatStateAdapter", () => ({
  useChatStateAdapter: () => ({
    state: {
      messages: [],
      knowledgeBases: [],
      llmSelection: null,
      personaSelection: "",
      resourceSelection: captured.selection,
      workspaceId: "ws-1",
      isStreaming: false,
    },
    sendMessage: vi.fn(),
    submitUserReply: vi.fn(),
    cancelStreamingTurn: () => undefined,
    setKBs: () => undefined,
    setLLMSelection: () => undefined,
    setPersonaSelection: () => undefined,
    setResourceSelection: captured.setResourceSelection,
  }),
}));

vi.mock("@/hooks/useWorkspaceChatActions", () => ({
  useWorkspaceChatActions: () => ({
    capabilities: [],
    activeCapabilityValue: "",
    selectCapability: () => undefined,
  }),
}));

vi.mock("@/hooks/useContextBudget", () => ({
  useContextBudget: () => null,
}));

vi.mock("@/hooks/useChatWorkspaces", () => ({
  useChatWorkspaces: () => ({ workspaces: [], error: "" }),
}));

vi.mock("@/hooks/useComposerResources", () => ({
  useComposerResources: () => captured.catalog,
}));

vi.mock("@/components/chat/home/StandaloneComposer", () => ({
  default: (props: {
    resourceCatalog?: ComposerResourceCatalog;
    resourceSelection?: ResourceSelection;
    onResourceSelectionChange?: (selection: ResourceSelection) => void;
  }) => {
    captured.props = props;
    return <div>composer</div>;
  },
}));

const { MasteryComposer } = await import(
  "@/components/space/learning/MasteryComposer"
);

describe("MasteryComposer resource wiring", () => {
  beforeEach(() => {
    captured.props = null;
    captured.setResourceSelection.mockClear();
  });

  it("passes catalog, selection, and the session setter through to the composer", () => {
    render(<MasteryComposer placeholder="Ask" />);
    expect(captured.props?.resourceCatalog).toEqual(captured.catalog);
    expect(captured.props?.resourceSelection).toEqual(captured.selection);
    expect(captured.props?.onResourceSelectionChange).toBe(
      captured.setResourceSelection,
    );

    const next = { skills: ["skill-1", "skill-2"], mcp: ["mcp-1"] };
    captured.props?.onResourceSelectionChange?.(next);
    expect(captured.setResourceSelection).toHaveBeenCalledWith(next);
  });
});
