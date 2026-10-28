/** Read-only previews of incomplete JSON. Never used to execute a tool. */
import type { Emit, JsonRecord, ToolCall } from "../native/types.js";
import { askPayload } from "./ask-user.js";

function partialJson(source: string): unknown {
  let i = 0;
  const whitespace = () => {
    while (/\s/.test(source[i] || "x")) i++;
  };
  const string = () => {
    const start = i++;
    let escaped = false;
    while (i < source.length) {
      const char = source[i++]!;
      if (!escaped && char === '"')
        return JSON.parse(source.slice(start, i)) as string;
      if (!escaped && char === "\\") escaped = true;
      else escaped = false;
    }
    // An incomplete escape is omitted until its full code point arrives.
    let tail = source.slice(start + 1).replace(/\\(?:u[\da-f]{0,3})?$/i, "");
    try {
      return JSON.parse(`"${tail}"`) as string;
    } catch {
      return "";
    }
  };
  const value = (depth: number): unknown => {
    if (depth > 20) throw new Error("Preview nesting limit");
    whitespace();
    const char = source[i];
    if (char === '"') return string();
    if (char === "{" || char === "[") {
      i++;
      const object: JsonRecord = {},
        array: unknown[] = [];
      while (i < source.length) {
        whitespace();
        if (source[i] === (char === "{" ? "}" : "]")) {
          i++;
          break;
        }
        if (char === "{") {
          if (source[i] !== '"') break;
          const key = string();
          whitespace();
          if (source[i++] !== ":") break;
          const child = value(depth + 1);
          if (child === undefined) break;
          if (!["__proto__", "constructor", "prototype"].includes(key))
            object[key] = child;
        } else {
          const child = value(depth + 1);
          if (child === undefined) break;
          array.push(child);
        }
        whitespace();
        if (source[i] === ",") i++;
        else break;
      }
      return char === "{" ? object : array;
    }
    const token = source
      .slice(i)
      .match(/^(?:true|false|null|-?\d+(?:\.\d+)?)/)?.[0];
    if (!token) return undefined;
    i += token.length;
    return JSON.parse(token);
  };
  return value(0);
}

export class AskUserDraft {
  private states = new Map<
    string,
    { length: number; at: number; payload: string; shape: number[] }
  >();
  constructor(
    private emit: Emit,
    private trace: JsonRecord,
  ) {}
  async observe(call: ToolCall, force = false): Promise<void> {
    if (call.name !== "ask_user" || call.arguments.length > 131_072) return;
    const previous = this.states.get(call.id),
      now = Date.now();
    if (
      previous &&
      !force &&
      (call.arguments.length - previous.length < 24 || now - previous.at < 180)
    )
      return;
    let payload: JsonRecord;
    try {
      payload = askPayload(partialJson(call.arguments) as JsonRecord);
    } catch {
      return;
    }
    const questions = payload.questions as JsonRecord[];
    const shape = [
      questions.length,
      ...questions.map((q) => (q.options as unknown[]).length),
    ];
    if (previous?.shape.some((size, i) => size > (shape[i] ?? 0))) return;
    const serialized = JSON.stringify(payload);
    this.states.set(call.id, {
      length: call.arguments.length,
      at: now,
      payload: serialized,
      shape,
    });
    if (previous?.payload === serialized) return;
    await this.emit({
      type: "progress",
      content: "",
      metadata: {
        ...this.trace,
        trace_kind: "ask_user_draft",
        tool_name: "ask_user",
        draft_call_id: call.id.split("|", 1)[0],
        ask_user_draft: payload,
      },
    });
  }
}
