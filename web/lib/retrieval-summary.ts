type ToolTraceLike = {
  name?: unknown;
  arguments?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  sources?: Array<Record<string, unknown>> | null;
};

export interface RetrievalSummaryItem {
  kbName: string;
  files: string[];
  chunkCount: number;
}

export interface RetrievalSummary {
  knowledgeBases: RetrievalSummaryItem[];
  totalFiles: number;
  totalChunks: number;
}

function coerceObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function coerceObjectArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value
        .map((item) => coerceObject(item))
        .filter((item): item is Record<string, unknown> => item !== null)
    : [];
}

function normalizeSourceLabel(source: Record<string, unknown>): string {
  const title = String(source.title || "").trim();
  if (title) return title;

  const rawSource = String(source.source || "").trim();
  if (!rawSource) return "";

  const normalized = rawSource.replace(/\\/g, "/");
  const tail = normalized.split("/").filter(Boolean).pop();
  return (tail || rawSource).trim();
}

export function extractRetrievalSummary(
  metadata: Record<string, unknown> | null | undefined,
): RetrievalSummary | null {
  const toolTraces = Array.isArray(metadata?.tool_traces)
    ? (metadata?.tool_traces as ToolTraceLike[])
    : [];

  const kbMap = new Map<string, { files: Set<string>; chunkCount: number }>();

  for (const trace of toolTraces) {
    if (trace?.name !== "rag") continue;

    const traceMetadata = coerceObject(trace.metadata);
    const traceArguments = coerceObject(trace.arguments);
    const ragSources = coerceObjectArray(traceMetadata?.sources);
    const sourceHints = coerceObjectArray(trace.sources);
    const kbName =
      String(traceArguments?.kb_name || sourceHints[0]?.kb_name || "").trim() ||
      "Knowledge Base";

    const entry = kbMap.get(kbName) || { files: new Set<string>(), chunkCount: 0 };
    entry.chunkCount += ragSources.length;

    for (const source of ragSources) {
      const label = normalizeSourceLabel(source);
      if (label) entry.files.add(label);
    }

    kbMap.set(kbName, entry);
  }

  if (!kbMap.size) return null;

  const knowledgeBases = Array.from(kbMap.entries()).map(([kbName, entry]) => ({
    kbName,
    files: Array.from(entry.files),
    chunkCount: entry.chunkCount,
  }));

  return {
    knowledgeBases,
    totalFiles: knowledgeBases.reduce((sum, item) => sum + item.files.length, 0),
    totalChunks: knowledgeBases.reduce((sum, item) => sum + item.chunkCount, 0),
  };
}
