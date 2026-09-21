import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";

initI18n("en");

/**
 * #1534: a Mastery Path conversation showed no Skills entry in Resources while
 * home chat did, even though the workspace's persisted policy already allowed
 * nine skills.
 *
 * The row is not gated on a capability allowlist — `ChatComposer` shows it when
 * the caller passes a catalog with entries and a selection setter. Mastery
 * renders through `StandaloneComposer`, which simply had no such props, so the
 * row could never appear no matter what the workspace allowed. These tests pin
 * the wiring from the session's workspace to the composer, and the fact that a
 * pick lands on session state (which every following turn carries) rather than
 * on a per-send copy that `start_turn` would never see.
 */
type ComposerResourceProps = {
  resourceCatalog?: {
    skills: { id: string; name: string }[];
    mcp: { id: string; name: string }[];
  };
  resourceSelection?: { skills: string[]; mcp: string[] };
  onResourceSelectionChange?: (selection: {
    skills: string[];
    mcp: string[];
  }) => void;
};

const harness = vi.hoisted(() => ({
  setResourceSelection: vi.fn(),
  seenWorkspaceId: "unset" as string | null,
  composerProps: null as Record<string, unknown> | null,
  state: {
    messages: [],
    knowledgeBases: [],
    llmSelection: null,
    personaSelection: "",
    resourceSelection: { skills: [], mcp: [] },
    workspaceId: "ws-7",
    isStreaming: false,
  },
  catalog: {
    skills: [{ id: "s1", name: "Tutor" }],
    mcp: [{ id: "m1", name: "Filesystem" }],
  },
}));

vi.mock("@/features/chat/ChatStateAdapter", () => ({
  useChatStateAdapter: () => ({
    state: harness.state,
    sendMessage: () => undefined,
    submitUserReply: async () => true,
    cancelStreamingTurn: () => undefined,
    setKBs: () => undefined,
    setLLMSelection: () => undefined,
    setPersonaSelection: () => undefined,
    setResourceSelection: harness.setResourceSelection,
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
  useChatWorkspaces: () => ({ workspaces: [], error: null }),
}));

vi.mock("@/hooks/useComposerResources", () => ({
  useComposerResources: (workspaceId: string | null) => {
    harness.seenWorkspaceId = workspaceId;
    return harness.catalog;
  },
}));

/** Stands in for the real composer: records the props it was handed. */
vi.mock("@/components/chat/home/StandaloneComposer", () => ({
  default: (props: Record<string, unknown>) => {
    harness.composerProps = props;
    return null;
  },
}));

const { MasteryComposer } = await import(
  "@/components/space/learning/MasteryComposer"
);

describe("mastery composer resource pickers", () => {
  beforeEach(() => {
    harness.setResourceSelection.mockClear();
    harness.seenWorkspaceId = "unset";
    harness.composerProps = null;
  });

  it("offers this conversation's own workspace catalog", () => {
    render(<MasteryComposer placeholder="Ask" />);

    expect(harness.seenWorkspaceId).toBe("ws-7");
    const props = harness.composerProps as unknown as ComposerResourceProps;
    expect(props.resourceCatalog?.skills).toHaveLength(1);
    expect(props.resourceSelection).toEqual({ skills: [], mcp: [] });
    expect(typeof props.onResourceSelectionChange).toBe("function");
  });

  it("writes a pick back to the session, which is what every turn sends", () => {
    render(<MasteryComposer placeholder="Ask" />);
    const props = harness.composerProps as unknown as ComposerResourceProps;

    props.onResourceSelectionChange?.({ skills: ["s1"], mcp: [] });

    expect(harness.setResourceSelection).toHaveBeenCalledWith({
      skills: ["s1"],
      mcp: [],
    });
  });
});
