"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import { getChatCapability } from "@/features/capabilities/presentation";
import { useCapabilityCatalog } from "@/features/capabilities/useCapabilityCatalog";
import { getEnabledOptionalTools } from "@/lib/tools-settings";

/**
 * Keep a workspace's action selection on the same tool policy as Home.
 *
 * `pinnedCapability` makes the workspace run one action and only that one:
 * there is no menu, and the capability is asserted on mount so a session
 * resumed with something else stored still opens on the right loop. Mastery
 * uses it — its screen IS the tutor, so offering "Chat" there meant two ways
 * to reach the same tutor and no way to tell which one you were in. Reading
 * passes nothing and keeps the menu.
 */
export function useWorkspaceChatActions(
  options: { pinnedCapability?: string } = {},
) {
  const { pinnedCapability } = options;
  const { state, setCapability, setTools } = useChatStateAdapter();
  const { capabilities: catalogCapabilities } = useCapabilityCatalog();
  const workspaceCapabilities = useMemo(
    () =>
      pinnedCapability
        ? catalogCapabilities.filter(
            (capability) => capability.value === pinnedCapability,
          )
        : catalogCapabilities.filter(
            (capability) =>
              capability.value !== "course_study" &&
              capability.value !== "immersive_watching",
          ),
    [catalogCapabilities, pinnedCapability],
  );
  const [enabledOptionalTools, setEnabledOptionalTools] = useState<
    string[] | null
  >(null);

  const activeValue = pinnedCapability
    ? pinnedCapability
    : workspaceCapabilities.some(
          (capability) => capability.value === (state.activeCapability || ""),
        )
      ? state.activeCapability || ""
      : "";

  // Assert the pinned action rather than assuming it: the turn is built from
  // chat state, so a session that stored another capability would otherwise
  // send that one from a screen offering no way to change it.
  useEffect(() => {
    if (!pinnedCapability) return;
    if (state.activeCapability === pinnedCapability) return;
    setCapability(pinnedCapability);
  }, [pinnedCapability, setCapability, state.activeCapability]);
  const activeCapability = useMemo(
    () =>
      workspaceCapabilities.find(
        (capability) => capability.value === activeValue,
      ) ?? getChatCapability(activeValue),
    [activeValue, workspaceCapabilities],
  );
  // A pinned workspace has no menu to render.
  const offeredCapabilities = pinnedCapability ? [] : workspaceCapabilities;

  useEffect(() => {
    let cancelled = false;
    void getEnabledOptionalTools()
      .then((tools) => {
        if (!cancelled) setEnabledOptionalTools(tools);
      })
      .catch(() => {
        if (!cancelled) setEnabledOptionalTools([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (enabledOptionalTools === null) return;
    const allowed = new Set<string>(activeCapability.allowedTools);
    const next = enabledOptionalTools.filter((tool) => allowed.has(tool));
    const same =
      next.length === state.enabledTools.length &&
      next.every((tool, index) => tool === state.enabledTools[index]);
    if (!same) setTools(next);
  }, [
    activeCapability.allowedTools,
    enabledOptionalTools,
    setTools,
    state.enabledTools,
  ]);

  const selectCapability = useCallback(
    (value: string) => {
      if (pinnedCapability) return;
      const selected = workspaceCapabilities.find(
        (capability) => capability.value === value,
      );
      const next =
        selected ?? workspaceCapabilities[0] ?? getChatCapability("");
      setCapability(next.value || null);
      if (enabledOptionalTools !== null) {
        const allowed = new Set<string>(next.allowedTools);
        setTools(enabledOptionalTools.filter((tool) => allowed.has(tool)));
      }
    },
    [
      enabledOptionalTools,
      pinnedCapability,
      setCapability,
      setTools,
      workspaceCapabilities,
    ],
  );

  return {
    capabilities: offeredCapabilities,
    activeCapabilityValue: activeValue,
    selectCapability,
  };
}
