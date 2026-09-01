"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useUnifiedChat } from "@/context/UnifiedChatContext";
import {
  WORKSPACE_CHAT_CAPABILITIES,
  getChatCapability,
} from "@/lib/chat-capabilities";
import { getEnabledOptionalTools } from "@/lib/tools-settings";

/** Keep Reading/Mastery action selection on the same tool policy as Home. */
export function useWorkspaceChatActions() {
  const { state, setCapability, setTools } = useUnifiedChat();
  const [enabledOptionalTools, setEnabledOptionalTools] = useState<
    string[] | null
  >(null);

  const activeValue = WORKSPACE_CHAT_CAPABILITIES.some(
    (capability) => capability.value === (state.activeCapability || ""),
  )
    ? state.activeCapability || ""
    : "";
  const activeCapability = useMemo(
    () => getChatCapability(activeValue),
    [activeValue],
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
      const selected = WORKSPACE_CHAT_CAPABILITIES.find(
        (capability) => capability.value === value,
      );
      const next = selected ?? WORKSPACE_CHAT_CAPABILITIES[0];
      setCapability(next.value || null);
      if (enabledOptionalTools !== null) {
        const allowed = new Set<string>(next.allowedTools);
        setTools(enabledOptionalTools.filter((tool) => allowed.has(tool)));
      }
    },
    [enabledOptionalTools, setCapability, setTools],
  );

  return {
    capabilities: WORKSPACE_CHAT_CAPABILITIES,
    activeCapabilityValue: activeValue,
    selectCapability,
  };
}
