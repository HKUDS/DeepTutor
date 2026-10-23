import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CHAT_CAPABILITIES } from "@/features/capabilities/presentation";

const captured = vi.hoisted(() => ({
  activeCapability: null as string | null,
  catalogLoading: false,
  setCapability: vi.fn(),
}));

vi.mock("@/features/chat/ChatStateAdapter", () => ({
  useChatStateAdapter: () => ({
    state: { activeCapability: captured.activeCapability, enabledTools: [] },
    setCapability: captured.setCapability,
    setTools: vi.fn(),
  }),
}));

vi.mock("@/features/capabilities/useCapabilityCatalog", () => ({
  useCapabilityCatalog: () => ({
    capabilities: CHAT_CAPABILITIES,
    isLoading: captured.catalogLoading,
  }),
}));

vi.mock("@/lib/tools-settings", () => ({
  getEnabledOptionalTools: () => Promise.resolve([]),
}));

const { useWorkspaceChatActions } = await import(
  "@/hooks/useWorkspaceChatActions"
);

describe("useWorkspaceChatActions with a stored action the workspace hides", () => {
  beforeEach(() => {
    captured.activeCapability = null;
    captured.catalogLoading = false;
    captured.setCapability.mockClear();
  });

  it("sends Chat when Course Study is carried into Reading", async () => {
    captured.activeCapability = "course_study";
    const { result } = renderHook(() => useWorkspaceChatActions());
    await act(async () => {});

    expect(result.current.activeCapabilityValue).toBe("");
    expect(captured.setCapability).toHaveBeenCalledWith(null);
  });

  it("keeps an action the workspace offers", async () => {
    captured.activeCapability = "deep_solve";
    const { result } = renderHook(() => useWorkspaceChatActions());
    await act(async () => {});

    expect(result.current.activeCapabilityValue).toBe("deep_solve");
    expect(captured.setCapability).not.toHaveBeenCalled();
  });

  it("waits for the catalog before resetting an unknown action", async () => {
    captured.activeCapability = "plugin_only_action";
    captured.catalogLoading = true;
    renderHook(() => useWorkspaceChatActions());
    await act(async () => {});

    expect(captured.setCapability).not.toHaveBeenCalled();
  });

  it("still asserts a pinned action", async () => {
    captured.activeCapability = "course_study";
    renderHook(() =>
      useWorkspaceChatActions({ pinnedCapability: "mastery_path" }),
    );
    await act(async () => {});

    expect(captured.setCapability).toHaveBeenCalledWith("mastery_path");
    expect(captured.setCapability).not.toHaveBeenCalledWith(null);
  });
});
