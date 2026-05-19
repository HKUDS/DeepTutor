export type ChatRetrievalMode = "auto" | "kb_only" | "kb_web" | "off";

export interface AppliedRetrievalSelection {
  enabledTools: string[];
  knowledgeBases: string[];
}

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values));
}

export function applyChatRetrievalMode(
  enabledTools: string[],
  knowledgeBases: string[],
  mode: ChatRetrievalMode,
): AppliedRetrievalSelection {
  const normalizedTools = uniqueStrings(enabledTools);
  const normalizedKbs = uniqueStrings(knowledgeBases);

  if (mode === "auto") {
    return {
      enabledTools: normalizedTools,
      knowledgeBases: normalizedKbs,
    };
  }

  if (mode === "kb_only") {
    return {
      enabledTools: normalizedTools.filter((tool) => tool !== "web_search"),
      knowledgeBases: normalizedKbs,
    };
  }

  if (mode === "kb_web") {
    return {
      enabledTools: uniqueStrings([...normalizedTools, "web_search"]),
      knowledgeBases: normalizedKbs,
    };
  }

  return {
    enabledTools: normalizedTools.filter((tool) => tool !== "web_search"),
    knowledgeBases: [],
  };
}
