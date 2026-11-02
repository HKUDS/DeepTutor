import { randomUUID } from "node:crypto";
import type {
  Emit,
  JsonRecord,
  NativeInput,
  Round,
  ToolSchema,
} from "./types.js";
import { Conversation } from "../context/conversation.js";
import { complete, type Completion } from "../providers/chat-completions.js";
import { ThinkFilter } from "../providers/think-filter.js";
import { AskUserDraft } from "../tools/ask-user-draft.js";

export async function modelRound(
  input: NativeInput,
  conversation: Conversation,
  tools: ToolSchema[],
  emit: Emit,
  signal: AbortSignal,
  settling: boolean,
  first: boolean,
): Promise<Round> {
  const id = `${input.source}-${input.stage}-${randomUUID()}`;
  const trace: JsonRecord = {
    call_id: id,
    trace_id: id,
    phase: input.stage,
    label: settling
      ? input.copy.final_response || "Final response"
      : input.copy.exploring || "Exploring",
    call_kind: "agent_loop_round",
    trace_role: settling ? "response" : "explore",
    trace_group: "stage",
    native_runtime: "typescript",
  };
  const projected = conversation.project(tools);
  if (projected.snipped)
    await emit({
      type: "progress",
      content:
        input.copy.context_window_guard ||
        "Context was shortened for this request.",
      metadata: { trace_kind: "warning" },
    });
  await emit({
    type: "progress",
    content: String(trace.label),
    metadata: { ...trace, trace_kind: "call_status", call_state: "running" },
  });
  const deferred: Round["deferred"] = [];
  const filter = new ThinkFilter();
  let visible = "",
    inlineReasoning = "";
  const drafts = new AskUserDraft(emit, trace);
  const piece = async (kind: "content" | "thinking", text: string) => {
    if (!text) return;
    if (kind === "content") visible += text;
    else inlineReasoning += text;
    const event = {
      type: kind,
      content: text,
      metadata: { ...trace, trace_kind: "llm_chunk" },
    };
    if (kind === "content" && input.deferOutput) {
      const last = deferred.at(-1);
      if (last?.type === "content" && last.content.length + text.length <= 8192)
        last.content += text;
      else deferred.push(event);
    } else await emit(event);
  };
  let response: Completion;
  try {
    response = await complete(
      input.provider,
      projected.messages,
      tools,
      first ? input.initialToolChoice : null,
      signal,
      async (kind, text, call) => {
        if (kind === "tool_arguments") {
          if (call) await drafts.observe(call);
          return;
        }
        if (kind === "thinking") {
          await piece(kind, text);
          return;
        }
        for (const [type, segment] of filter.feed(text))
          await piece(type, segment);
      },
    );
  } catch (error) {
    if (!signal.aborted)
      await emit({
        type: "progress",
        content: "",
        metadata: { ...trace, trace_kind: "call_status", call_state: "error" },
      });
    throw error;
  }
  for (const call of response.calls) await drafts.observe(call, true);
  for (const [kind, text] of filter.feed("", true)) await piece(kind, text);
  const usage = Object.keys(response.usage).length
    ? response.usage
    : {
        prompt_tokens: Number(conversation.budget().used_tokens || 0),
        completion_tokens: Math.ceil(
          (visible.length + response.reasoning.length) / 3.5,
        ),
        estimated: true,
      };
  const metadata = {
    ...trace,
    trace_kind: "call_status",
    call_state: "complete",
    call_role: response.calls.length ? "narration" : "finish",
    answer_visible: true,
    finish_reason: response.finishReason || "stop",
    requested_max_tokens: input.seed.outputTokens,
    usage_reported: Object.keys(response.usage).length > 0,
    ...usage,
    output_chars: response.text.length + response.reasoning.length,
    reasoning_chars: inlineReasoning.length,
    content_chars: visible.length,
    tool_call_count: response.calls.length,
  };
  if (input.deferOutput)
    deferred.push({ type: "progress", content: "", metadata });
  else await emit({ type: "progress", content: "", metadata });
  return {
    text: visible,
    reasoning: inlineReasoning,
    toolCalls: response.calls,
    usage,
    finishReason: response.finishReason,
    trace: metadata,
    deferred,
    requestTools: tools,
  };
}
