/**
 * Reading a tool's own metadata off a stream event.
 *
 * A tool returns `ToolResult.metadata`, but that is not what arrives at the
 * top level of the event: the dispatcher nests it under `tool_metadata`
 * alongside its own trace keys (`runtime/agentic/tool_dispatch.py`). Reading
 * the top level looks right and type-checks fine, and silently finds nothing.
 *
 * Eleven modules used to each carry their own three-line unwrap and their own
 * paragraph explaining that. One fact about the wire format, one place.
 */

export type MetadataRecord = Record<string, unknown>;

function asRecord(value: unknown): MetadataRecord | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as MetadataRecord)
    : null;
}

/**
 * The tool's own metadata, or null when the event carries none.
 *
 * Strict: only the nested block counts. Use this when the nesting is the proof
 * that a real tool produced the payload — a caller-synthesised event must not
 * be able to pass itself off as one.
 */
export function toolResultMetadata(metadata: unknown): MetadataRecord | null {
  return asRecord(asRecord(metadata)?.tool_metadata);
}

/**
 * The tool's metadata, falling back to the top level when it is not nested.
 *
 * Lenient, and for callers that read several keys out of the same block:
 * whichever record answered is the one every key comes from.
 */
export function toolResultScope(metadata: unknown): MetadataRecord | null {
  const outer = asRecord(metadata);
  if (!outer) return null;
  return asRecord(outer.tool_metadata) ?? outer;
}

/**
 * One key out of the tool's metadata, or undefined.
 *
 * Lenient: falls back to the top level, for surfaces whose events are
 * sometimes emitted directly rather than through the dispatcher.
 */
export function toolResultPayload(metadata: unknown, key: string): unknown {
  const outer = asRecord(metadata);
  if (!outer) return undefined;
  const nested = asRecord(outer.tool_metadata);
  const value = nested ? nested[key] : undefined;
  return value === undefined ? outer[key] : value;
}
