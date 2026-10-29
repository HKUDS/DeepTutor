import type { JsonRecord, ToolResult } from "../native/types.js";
import { record } from "../native/types.js";
import { result } from "./workspace.js";

const text = (value: unknown) =>
  value == null
    ? ""
    : String(value)
        .replace(/\\u([\da-f]{4})/gi, (_, code: string) =>
          String.fromCharCode(parseInt(code, 16)),
        )
        .trim();
function clip(value: unknown, limit: number, ellipsis = true): string | null {
  const chars = [...text(value)];
  return chars.length > limit
    ? chars.slice(0, limit).join("").trimEnd() + (ellipsis ? "…" : "")
    : chars.join("") || null;
}
const key = (label: string) => label.replace(/\s/g, "").toLowerCase();

export function askPayload(args: JsonRecord): JsonRecord {
  const raw =
    args.questions ??
    (args.question == null
      ? []
      : [{ prompt: args.question, options: args.options }]);
  if (!Array.isArray(raw) || !raw.length)
    throw new Error("ask_user requires an array of questions");
  const ids = new Set<string>();
  const questions = raw.slice(0, 4).map((item, index) => {
    const q = record(item),
      prompt = clip(q.prompt ?? q.question, 800);
    if (!prompt) throw new Error("Each question requires a non-empty prompt");
    const original = text(q.id) || `q${index + 1}`;
    let id = original,
      suffix = 2;
    while (ids.has(id)) id = `${original}_${suffix++}`;
    ids.add(id);
    const free = q.allow_free_text == null ? true : Boolean(q.allow_free_text);
    if (q.options != null && !Array.isArray(q.options))
      throw new Error("Question options must be an array");
    const labels = new Set<string>(),
      bodies = new Set<string>();
    const options: { label: string; description: string | null }[] = [];
    for (const rawOption of (q.options ?? []) as unknown[]) {
      if (
        typeof rawOption !== "string" &&
        (!rawOption ||
          typeof rawOption !== "object" ||
          Array.isArray(rawOption))
      )
        continue;
      const option =
        typeof rawOption === "string"
          ? { label: rawOption }
          : record(rawOption);
      const label = clip(option.label, 120),
        description = clip(option.description, 200);
      if (
        !label ||
        labels.has(key(label)) ||
        (free && ["other", "其他", "其它"].includes(key(label)))
      )
        continue;
      const body = description?.replace(/\s+/g, " ").toLowerCase();
      if (body && bodies.has(body)) continue;
      labels.add(key(label));
      if (body) bodies.add(body);
      options.push({ label, description });
      if (options.length >= 8) break;
    }
    return {
      id,
      prompt,
      header: clip(q.header, 16, false),
      options,
      multi_select: Boolean(q.multi_select ?? q.multiSelect),
      allow_free_text: free,
      placeholder: clip(q.placeholder, 120),
    };
  });
  return { questions, intro: clip(args.intro, 400) };
}

export function askUser(args: JsonRecord): ToolResult {
  const payload = askPayload(args);
  const prompts = (payload.questions as JsonRecord[])
    .map((q) => q.prompt)
    .join(", ");
  return {
    ...result(`[awaiting user reply to: ${prompts}]`, { ask_user: payload }),
    pause: payload,
  };
}
