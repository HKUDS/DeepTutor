"use client";

import { useCallback, useMemo, useState } from "react";

import type { StartTurnInput } from "../model/start-turn";

export function pruneKnowledgeBases(
  selected: string[],
  available: ReadonlySet<string>,
): string[] {
  return selected.filter(
    (name, index) => available.has(name) && selected.indexOf(name) === index,
  );
}

export function capabilityLaunchIntent(input: {
  capability?: string | null;
  tools?: string[];
  courseId?: string | null;
}): Pick<StartTurnInput, "capability" | "tools" | "courseId"> {
  return {
    capability: input.capability ?? "chat",
    tools: [...(input.tools ?? [])],
    courseId: input.courseId?.trim() || null,
  };
}

export function useChatComposerController(initialContent = "") {
  const [content, setContent] = useState(initialContent);
  const [capability, setCapability] = useState<string | null>("chat");
  const canSubmit = useMemo(() => content.trim().length > 0, [content]);
  const clearAfterSend = useCallback(() => setContent(""), []);
  return {
    canSubmit,
    capability,
    clearAfterSend,
    content,
    setCapability,
    setContent,
  };
}
