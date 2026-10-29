import type {
  JsonRecord,
  Message,
  ProviderConfig,
  ToolCall,
  ToolSchema,
} from "../native/types.js";
import { record } from "../native/types.js";
import { sse } from "./sse.js";
import { withProviderLimit } from "./limits.js";
import { readBody } from "./body.js";
import { post } from "./http.js";

export interface Completion {
  text: string;
  reasoning: string;
  calls: ToolCall[];
  usage: JsonRecord;
  finishReason: string;
}
export type DeltaSink = (
  kind: "content" | "thinking" | "tool_arguments",
  text: string,
  call?: ToolCall,
) => Promise<void>;
export class ProviderFailure extends Error {
  constructor(
    message: string,
    readonly partialResponse: boolean,
  ) {
    super(message);
    this.name = "ProviderFailure";
  }
}

/** HTTP and provider wire compatibility live here, never in the scheduler. */
export async function complete(
  config: ProviderConfig,
  messages: Message[],
  tools: ToolSchema[],
  choice: string | null,
  signal: AbortSignal,
  emit: DeltaSink,
): Promise<Completion> {
  return withProviderLimit(config, signal, () =>
    request(config, messages, tools, choice, signal, emit),
  );
}

async function request(
  config: ProviderConfig,
  messages: Message[],
  tools: ToolSchema[],
  choice: string | null,
  signal: AbortSignal,
  emit: DeltaSink,
): Promise<Completion> {
  let body: JsonRecord = {
    ...config.completion,
    model: config.model,
    messages,
    stream: config.stream,
  };
  if (config.stream) body.stream_options = { include_usage: true };
  if (tools.length) {
    body.tools = tools;
    body.tool_choice = choice
      ? { type: "function", function: { name: choice } }
      : "auto";
  }
  const headers = { "Content-Type": "application/json", ...config.headers };
  if (
    config.apiKey &&
    !Object.keys(headers).some((key) => key.toLowerCase() === "authorization")
  )
    Object.assign(headers, { Authorization: `Bearer ${config.apiKey}` });
  const retryDelays = config.retryDelaysMs ?? [500, 1500];
  let retry = 0;
  const compatibility = new Set<string>();
  while (true) {
    signal.throwIfAborted();
    let observed = false;
    const controller = new AbortController();
    const abort = () => controller.abort(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    const connectTimeout = setTimeout(
      () => controller.abort(new Error("Provider response timeout")),
      90_000,
    );
    try {
      const response = await post(
        config.endpoint,
        headers,
        JSON.stringify(body),
        controller.signal,
      );
      clearTimeout(connectTimeout);
      if (!response.ok) {
        // Bound and inspect error bodies, but never send endpoint credentials or
        // a provider's echoed private request into diagnostics.
        const text = (
          await readBody(response.body, controller.signal, 65_536)
        ).toLowerCase();
        if (
          response.status === 400 &&
          body.stream_options &&
          /stream_options|include_usage/.test(text) &&
          !compatibility.has("usage")
        ) {
          compatibility.add("usage");
          body = { ...body };
          delete body.stream_options;
          continue;
        }
        if (
          response.status === 400 &&
          choice &&
          /tool_choice|tool choice/.test(text) &&
          /not supported|does not support|unsupported|not allowed|cannot be used/.test(
            text,
          ) &&
          !/missing field|failed to deserialize/.test(text) &&
          !compatibility.has("choice")
        ) {
          compatibility.add("choice");
          body = { ...body, tool_choice: "required" };
          continue;
        }
        if (
          response.status === 400 &&
          body.response_format &&
          /response_format|response format/.test(text) &&
          /not supported|unsupported|json_schema|json_object|not valid/.test(
            text,
          ) &&
          !compatibility.has("format")
        ) {
          compatibility.add("format");
          body = { ...body };
          delete body.response_format;
          continue;
        }
        if (![408, 429, 500, 502, 503, 504].includes(response.status))
          throw new ProviderFailure(
            `Model provider returned HTTP ${response.status}`,
            false,
          );
        throw new Error(`Model provider returned HTTP ${response.status}`);
      }
      const result: Completion = {
        text: "",
        reasoning: "",
        calls: [],
        usage: {},
        finishReason: "",
      };
      const calls = new Map<number, ToolCall>();
      let bytes = 0;
      const ingest = async (raw: unknown, oneShot = false) => {
        const frame = record(raw);
        if (frame.error)
          throw new Error("Model provider emitted a stream error");
        if (frame.usage && typeof frame.usage === "object")
          result.usage = record(frame.usage);
        const choices = frame.choices as JsonRecord[] | undefined;
        const first = choices?.[0];
        if (!first) return;
        if (first.finish_reason)
          result.finishReason = String(first.finish_reason);
        const delta = record((oneShot ? first.message : first.delta) ?? {});
        for (const [key, kind] of [
          ["content", "content"],
          ["reasoning_content", "thinking"],
        ] as const) {
          const value = delta[key];
          if (typeof value !== "string" || !value) continue;
          observed = true;
          bytes += value.length;
          if (bytes > 16_777_216)
            throw new Error("Provider output exceeds turn limit");
          if (kind === "content") result.text += value;
          else result.reasoning += value;
          await emit(kind, value);
        }
        for (const [position, item] of (
          (delta.tool_calls ?? []) as JsonRecord[]
        ).entries()) {
          observed = true;
          const index = Number(item.index ?? position);
          if (!Number.isSafeInteger(index) || index < 0 || index > 255)
            throw new Error("Invalid tool call index");
          const call = calls.get(index) ?? { id: "", name: "", arguments: "" };
          const fn = record(item.function ?? {});
          if (item.id) call.id = String(item.id);
          if (fn.name && String(fn.name) !== call.name)
            call.name += String(fn.name);
          const args = String(fn.arguments ?? "");
          call.arguments += args;
          if (call.arguments.length > 4_194_304)
            throw new Error("Tool arguments exceed limit");
          calls.set(index, call);
          if (args) await emit("tool_arguments", args, { ...call });
        }
      };
      if (config.stream && response.contentType.includes("text/event-stream")) {
        if (!response.body)
          throw new Error("Model provider returned no stream");
        let done = false;
        for await (const data of sse(response.body, controller.signal)) {
          if (data.trim() === "[DONE]") {
            done = true;
            break;
          }
          await ingest(JSON.parse(data));
        }
        if (!done && !result.finishReason)
          throw new Error("Model stream closed before completion");
      } else {
        const text = await readBody(
          response.body,
          controller.signal,
          16_777_216,
        );
        await ingest(JSON.parse(text), true);
      }
      result.calls = [...calls.entries()]
        .sort(([a], [b]) => a - b)
        .map(([, c]) => c);
      if (result.calls.some((c) => !c.id || !c.name))
        throw new Error("Incomplete tool identity");
      if (new Set(result.calls.map((c) => c.id)).size !== result.calls.length)
        throw new Error("Duplicate tool call identity");
      return result;
    } catch (error) {
      signal.throwIfAborted();
      if (
        observed ||
        error instanceof ProviderFailure ||
        retry >= retryDelays.length
      ) {
        throw new ProviderFailure(
          error instanceof Error ? error.message : "Provider request failed",
          observed,
        );
      }
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => {
          signal.removeEventListener("abort", cancel);
          resolve();
        }, retryDelays[retry++]!);
        const cancel = () => {
          clearTimeout(timer);
          signal.removeEventListener("abort", cancel);
          reject(signal.reason);
        };
        signal.addEventListener("abort", cancel, { once: true });
      });
    } finally {
      clearTimeout(connectTimeout);
      signal.removeEventListener("abort", abort);
      controller.abort();
    }
  }
}
