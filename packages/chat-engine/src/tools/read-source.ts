import type { JsonRecord, NativeInput, ToolResult } from "../native/types.js";
import { result } from "./workspace.js";

/** No filesystem or caller-supplied index: only the server-admitted source map. */
export function readSource(args: JsonRecord, input: NativeInput): ToolResult {
  const sources = input.toolRuntime?.read_source?.sources || {};
  const ids = Object.keys(sources);
  if (!ids.length)
    return result(
      "Error: no attached sources are available for this turn.",
      {},
      false,
    );
  if (args.source_id != null && typeof args.source_id !== "string")
    return result("Error: source_id must be a string.", {}, false);
  const id =
    String(args.source_id || "").trim() || (ids.length === 1 ? ids[0]! : "");
  if (!id)
    return result(
      "Error: source_id is required when multiple sources are available.",
      {},
      false,
    );
  const text = Object.hasOwn(sources, id) ? sources[id] : undefined;
  if (!text)
    return result(
      `Error: unknown source_id ${JSON.stringify(id)}. Valid ids for this turn: ${ids.sort().join(", ")}.`,
      {},
      false,
    );
  return result(text, { source_id: id, char_count: [...text].length });
}
