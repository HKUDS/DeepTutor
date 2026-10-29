/** Stateless model tools share the turn's provider transport and admission limits. */
import type {
  Emit,
  JsonRecord,
  NativeInput,
  ToolResult,
} from "../native/types.js";
import { complete } from "../providers/chat-completions.js";
import { visibleText } from "../providers/one-shot.js";
import { estimateText } from "../context/conversation.js";
import { result } from "./workspace.js";

export async function modelTool(
  name: string,
  args: JsonRecord,
  input: NativeInput,
  trace: JsonRecord,
  emit: Emit,
  signal: AbortSignal,
): Promise<ToolResult> {
  const runtime = input.toolRuntime?.[name];
  if (!runtime?.provider || !runtime.system)
    throw new Error("Missing admitted model-tool configuration");
  const key = name === "reason" ? "query" : "topic";
  if (typeof args[key] !== "string" || !args[key].trim())
    throw new Error(`${key} must be a nonempty string`);
  if (args.context != null && typeof args.context !== "string")
    throw new Error("context must be a string");
  const focus = args[key] as string;
  const context = Object.hasOwn(args, "context")
    ? String(args.context ?? "")
    : runtime.context || "";
  const parts =
    name === "reason"
      ? [
          ...(context ? [`## Context\n${context}`] : []),
          `## Reasoning Focus\n${focus}`,
        ]
      : [
          `## Topic\n${focus.trim()}`,
          ...(context.trim() ? [`## Context\n${context.trim()}`] : []),
        ];
  const prompt = parts.join("\n\n");
  const completion = await complete(
    runtime.provider,
    [
      { role: "system", content: runtime.system },
      { role: "user", content: prompt },
    ],
    [],
    null,
    signal,
    async () => {},
  );
  // A delegated tool's response belongs in its observation, never the main answer.
  const answer = visibleText(completion.text).trim();
  const usage = Object.keys(completion.usage).length
    ? completion.usage
    : {
        prompt_tokens: estimateText(runtime.system + prompt),
        completion_tokens: estimateText(completion.text + completion.reasoning),
        estimated: true,
      };
  await emit({
    type: "progress",
    content: "",
    metadata: {
      ...trace,
      trace_kind: "tool_model_usage",
      model: runtime.provider.model,
      ...usage,
    },
  });
  if (
    completion.calls.length ||
    !answer ||
    ["content_filter", "error"].includes(completion.finishReason)
  )
    return {
      ...result("The model tool did not produce a usable answer.", {}, false),
      usage,
    };
  const truncated = ["length", "max_tokens", "max_output_tokens"].includes(
    completion.finishReason,
  );
  return {
    ...result(answer, {
      [key]: focus,
      answer,
      model: runtime.provider.model,
      ...(truncated ? { truncated: true } : {}),
    }),
    usage,
  };
}
