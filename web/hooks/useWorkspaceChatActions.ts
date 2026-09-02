"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import { getChatCapability } from "@/features/capabilities/presentation";
import { useCapabilityCatalog } from "@/features/capabilities/useCapabilityCatalog";
import { getEnabledOptionalTools } from "@/lib/tools-settings";

/** Keep Reading/Mastery action selection on the same tool policy as Home. */
export function useWorkspaceChatActions() {
  const { state, setCapability, setTools } = useChatStateAdapter();
  const { capabilities: catalogCapabilities } = useCapabilityCatalog();
  const workspaceCapabilities = useMemo(
    () =>
      catalogCapabilities.filter(
        (capability) =>
          capability.value !== "course_study" &&
          capability.value !== "immersive_watching",
      ),
    [catalogCapabilities],
  );
  const [enabledOptionalTools, setEnabledOptionalTools] = useState<
    string[] | null
  >(null);

  const activeValue = workspaceCapabilities.some(
    (capability) => capability.value === (state.activeCapability || ""),
  )
    ? state.activeCapability || ""
    : "";
  const activeCapability = useMemo(
    () =>
      workspaceCapabilities.find(
        (capability) => capability.value === activeValue,
      ) ?? getChatCapability(activeValue),
    [activeValue, workspaceCapabilities],
  );

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
    [enabledOptionalTools, setCapability, setTools, workspaceCapabilities],
  );

  return {
    capabilities: workspaceCapabilities,
    activeCapabilityValue: activeValue,
    selectCapability,
  };
}
