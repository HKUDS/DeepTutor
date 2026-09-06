/** Collect RAG citation figures from turn stream events (no React). */

export type RagSourceFigure = {
  image_url: string;
  mime_type?: string;
  image_description?: string;
  title?: string;
  page?: string;
};

function isServableImageUrl(url: string): boolean {
  return (
    url.startsWith("/api/") ||
    url.startsWith("http://") ||
    url.startsWith("https://")
  );
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function figureFromSource(
  source: Record<string, unknown>,
  extra?: Partial<RagSourceFigure>,
): RagSourceFigure | null {
  const imageUrl = String(source.image_url || extra?.image_url || "").trim();
  if (!isServableImageUrl(imageUrl)) return null;
  const mime = String(source.mime_type || extra?.mime_type || "").trim();
  const description = String(
    source.image_description || extra?.image_description || "",
  ).trim();
  const title = String(source.title || extra?.title || "").trim();
  const page = String(source.page || extra?.page || "").trim();
  return {
    image_url: imageUrl,
    ...(mime ? { mime_type: mime } : {}),
    ...(description ? { image_description: description } : {}),
    ...(title ? { title } : {}),
    ...(page ? { page } : {}),
  };
}

function figuresFromSource(source: unknown): RagSourceFigure[] {
  const record = asRecord(source);
  if (!record) return [];
  const found: RagSourceFigure[] = [];
  const primary = figureFromSource(record);
  if (primary) found.push(primary);
  const nested = record.images;
  if (Array.isArray(nested)) {
    for (const item of nested) {
      const nestedRecord = asRecord(item);
      if (!nestedRecord) continue;
      const figure = figureFromSource(nestedRecord, {
        title: String(record.title || ""),
      });
      if (figure) found.push(figure);
    }
  }
  return found;
}

function sourcesFromMetadata(metadata: unknown): unknown[] {
  const record = asRecord(metadata);
  if (!record) return [];
  if (Array.isArray(record.sources)) return record.sources;
  const nested = asRecord(record.metadata);
  if (nested && Array.isArray(nested.sources)) return nested.sources;
  const toolMeta = asRecord(record.tool_metadata);
  if (toolMeta && Array.isArray(toolMeta.sources)) return toolMeta.sources;
  return [];
}

export function collectRagSourceFigures(
  events:
    | Array<{ type?: string; metadata?: Record<string, unknown> | null }>
    | undefined,
): RagSourceFigure[] {
  if (!events?.length) return [];
  const seen = new Set<string>();
  const figures: RagSourceFigure[] = [];
  for (const event of events) {
    for (const source of sourcesFromMetadata(event.metadata)) {
      for (const figure of figuresFromSource(source)) {
        if (seen.has(figure.image_url)) continue;
        seen.add(figure.image_url);
        figures.push(figure);
      }
    }
  }
  return figures;
}
