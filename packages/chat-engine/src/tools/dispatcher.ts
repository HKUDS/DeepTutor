import { randomUUID } from "node:crypto";
import type {
  Dispatch,
  Emit,
  JsonRecord,
  LegacyPort,
  NativeInput,
  ToolCall,
  ToolResult,
  ToolSpec,
} from "../native/types.js";
import { record } from "../native/types.js";
import { askUser } from "./ask-user.js";
import { result, workspaceTool } from "./workspace.js";
import { modelTool } from "./model-tool.js";
import { readMemory } from "./read-memory.js";
import { readSource } from "./read-source.js";

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}
const pauseLast = new Set(["ask_user", "workspace_export"]);
export class ToolDispatcher {
  nativeCalls = 0;
  legacyCalls = 0;
  constructor(
    readonly input: NativeInput,
    readonly legacy: LegacyPort,
    readonly emit: Emit,
    readonly signal: AbortSignal,
    readonly onResult?: (call: ToolCall, output: ToolResult) => Promise<void>,
  ) {}

  async run(
    calls: ToolCall[],
    specs: ToolSpec[],
    iteration: number,
    rejection = "",
  ): Promise<Dispatch> {
    const admitted = new Map(
      specs.map((spec) => [spec.schema.function.name, spec]),
    );
    const seen = new Map<string, string>();
    const prepared = calls.slice(0, 15).map((call, index) => {
      let args: JsonRecord = {},
        failure = "";
      try {
        args = record(JSON.parse(call.arguments || "{}"));
      } catch {
        failure = "Tool arguments must be a valid JSON object";
      }
      // Private server-owned fields cannot be supplied by model output.
      args = Object.fromEntries(
        Object.entries(args).filter(([key]) => !key.startsWith("_")),
      );
      const spec = admitted.get(call.name),
        key = pauseLast.has(call.name)
          ? "pause"
          : `${call.name}:${canonical(args)}`;
      const duplicate = seen.get(key);
      seen.set(key, duplicate ?? call.id);
      const id = `${this.input.source}-native-tool-${randomUUID()}`;
      const meta: JsonRecord = {
        call_id: id,
        trace_id: id,
        phase: this.input.stage,
        trace_role: "tool",
        trace_group: "tool_call",
        call_kind: "tool_planning",
        label: this.input.copy.tool_call || "Tool call",
        tool_call_id: call.id,
        tool_name: call.name,
        tool_index: index,
        iteration_index: iteration,
        session_id: this.input.sessionId,
      };
      return {
        call,
        args,
        spec,
        failure,
        duplicate,
        meta,
        hidden: !!duplicate && pauseLast.has(call.name),
      };
    });
    for (const item of prepared) {
      if (item.hidden) continue;
      const display = Object.fromEntries(
        Object.entries(item.args).filter(
          ([key]) => !item.spec?.sensitive.includes(key),
        ),
      );
      await this.emit({
        type: "tool_call",
        content: item.call.name,
        metadata: { ...item.meta, trace_kind: "tool_call", args: display },
      });
    }
    const execute = async (index: number): Promise<ToolResult> => {
      const item = prepared[index]!;
      this.signal.throwIfAborted();
      const publish = async (output: ToolResult): Promise<ToolResult> => {
        // Checkpoint the result before making completion visible to consumers.
        await this.onResult?.(item.call, output);
        if (!item.hidden && !item.duplicate)
          await this.emit({
            type: "progress",
            content: "",
            metadata: {
              ...item.meta,
              trace_kind: "call_status",
              call_state: output.success ? "complete" : "error",
            },
          });
        if (!item.hidden)
          await this.emit({
            type: "tool_result",
            content: output.content,
            metadata: {
              ...item.meta,
              tool: item.call.name,
              trace_kind: "tool_result",
              tool_metadata: output.metadata,
            },
          });
        return output;
      };
      if (item.duplicate)
        return publish(
          result(
            `[Duplicate parallel call skipped; see result ${item.duplicate}. Do not repeat an identical call in one batch.]`,
          ),
        );
      await this.emit({
        type: "progress",
        content: "",
        metadata: {
          ...item.meta,
          trace_kind: "call_status",
          call_state: "running",
        },
      });
      let output: ToolResult;
      try {
        if (rejection) throw new Error(rejection);
        if (item.failure) throw new Error(item.failure);
        if (!item.spec)
          throw new Error(
            `Tool is not admitted for this turn: ${item.call.name}`,
          );
        const required = item.spec.schema.function.parameters.required;
        if (Array.isArray(required))
          for (const key of required) {
            const value = item.args[String(key)];
            if (value == null || (typeof value === "string" && !value.trim()))
              throw new Error(`Missing required argument: ${key}`);
          }
        if (item.spec.native) {
          this.nativeCalls++;
          output = ["read_memory", "partner_read"].includes(item.call.name)
            ? await readMemory(item.call.name, this.input, this.signal)
            : item.call.name === "ask_user"
              ? askUser(item.args)
              : item.call.name === "read_source"
                ? readSource(item.args, this.input)
                : ["reason", "brainstorm"].includes(item.call.name)
                  ? await modelTool(
                      item.call.name,
                      item.args,
                      this.input,
                      item.meta,
                      this.emit,
                      this.signal,
                    )
                  : await workspaceTool(
                      item.call.name,
                      item.args,
                      this.input,
                      this.signal,
                    );
        } else {
          this.legacyCalls++;
          output = (await this.legacy("legacy_tool", {
            name: item.call.name,
            args: item.args,
            trace: item.meta,
          })) as ToolResult;
        }
        if (
          !output ||
          typeof output.content !== "string" ||
          typeof output.success !== "boolean"
        )
          throw new Error("Invalid tool result");
      } catch (error) {
        this.signal.throwIfAborted();
        output = result(
          `${item.call.name} failed: ${error instanceof Error ? error.message : "Tool failure"}`,
          {},
          false,
        );
      }
      // UI results arrive in completion order; the model transcript below stays
      // in assistant source order. A slow tool must not hide completed work.
      return publish(output);
    };
    const outputs = new Map<number, ToolResult>();
    const rebind = prepared
      .map((p, i) => (this.input.rebindingTools.includes(p.call.name) ? i : -1))
      .filter((i) => i >= 0);
    const pauses = prepared
      .map((p, i) =>
        pauseLast.has(p.call.name) && !rebind.includes(i) ? i : -1,
      )
      .filter((i) => i >= 0);
    const ordinary = prepared
      .map((_, i) => i)
      .filter((i) => !rebind.includes(i) && !pauses.includes(i));
    // Each Python compatibility operation re-resolves its scoped arguments at
    // execution time, after any prior rebinding tool has completed.
    for (const index of rebind) outputs.set(index, await execute(index));
    await Promise.all(
      ordinary.map(async (index) => {
        outputs.set(index, await execute(index));
      }),
    );
    for (const index of pauses) outputs.set(index, await execute(index));
    const dispatch: Dispatch = {
      messages: [],
      modelMessages: [],
      sources: [],
      metadataById: {},
      pause: null,
      terminate: null,
      usage: [],
    };
    let images = 0;
    for (const [index, item] of prepared.entries()) {
      const output = outputs.get(index)!;
      if (output.usage) dispatch.usage!.push(output.usage);
      dispatch.messages.push({
        role: "tool",
        tool_call_id: item.call.id,
        name: item.call.name,
        content: output.content,
      });
      dispatch.sources.push(...output.sources);
      dispatch.metadataById[item.call.id] = output.metadata;
      if (
        output.modelMessage?.role === "user" &&
        Array.isArray(output.modelMessage.content)
      ) {
        const count = output.modelMessage.content.filter(
          (x: JsonRecord) => x.type === "image_url",
        ).length;
        if (count > 0 && images + count <= 2) {
          dispatch.modelMessages.push(output.modelMessage);
          images += count;
        }
      }
      if (output.pause && !dispatch.pause)
        dispatch.pause = {
          callId: item.call.id,
          name: item.call.name,
          payload: output.pause,
        };
      if (output.terminate && !dispatch.terminate)
        dispatch.terminate = {
          name: item.call.name,
          content: output.content,
          metadata: output.metadata,
        };
    }
    for (const call of calls.slice(15))
      dispatch.messages.push({
        role: "tool",
        tool_call_id: call.id,
        name: call.name,
        content: "Tool call not executed: this round is limited to 15 calls.",
      });
    return dispatch;
  }
}
