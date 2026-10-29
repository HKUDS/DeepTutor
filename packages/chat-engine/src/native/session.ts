import { HostFailure } from "../core/contracts.js";
import type {
  LoopHost,
  LoopState,
  Operation,
  Operations,
} from "../core/contracts.js";
import { runLoop } from "../core/run-loop.js";
import { Conversation } from "../context/conversation.js";
import { ProviderFailure } from "../providers/chat-completions.js";
import { ToolDispatcher } from "../tools/dispatcher.js";
import { EventCoalescer } from "./event-coalescer.js";
import { modelRound } from "./model-round.js";
import type {
  Dispatch,
  Emit,
  JsonRecord,
  LegacyPort,
  NativeInput,
  NativeResult,
  Round,
  ToolSpec,
} from "./types.js";
import { record, validateNativeInput, validateToolRuntime } from "./types.js";

export class NativeSession implements LoopHost {
  private readonly conversation: Conversation;
  private readonly dispatcher: ToolDispatcher;
  private round: Round | undefined;
  private dispatch: Dispatch | undefined;
  private tools: ToolSpec[];
  private continued: string[] = [];
  private response = "";
  private completed = false;
  private redirect = "";
  private override: string | null = null;
  private sources: JsonRecord[] = [];
  private usage: JsonRecord[] = [];
  private refreshHost = false;
  private state: LoopState = {
    rounds: 0,
    exploration_rounds: 0,
    settlement_rounds: 0,
    tool_steps: 0,
    reasoning_budget_recoveries: 0,
  };
  constructor(
    readonly input: NativeInput,
    readonly legacy: LegacyPort,
    readonly emit: Emit,
    readonly signal: AbortSignal,
  ) {
    this.conversation = new Conversation(input.seed);
    this.tools = input.tools;
    this.dispatcher = new ToolDispatcher(
      input,
      legacy,
      emit,
      signal,
      async (call, output) => {
        this.conversation.resolveTool(call.id, output.content);
        await this.checkpoint();
      },
    );
  }
  async run(): Promise<NativeResult> {
    await this.checkpoint();
    this.state = await runLoop(this, this.input.config, this.signal);
    await this.checkpoint();
    return {
      state: this.state,
      response: this.response,
      completed: this.completed,
      sources: this.sources,
      contextBudget: this.conversation.budget(),
      usage: this.usage,
      nativeToolCalls: this.dispatcher.nativeCalls,
      legacyToolCalls: this.dispatcher.legacyCalls,
    };
  }
  async invoke<K extends Operation>(
    operation: K,
    args: Operations[K]["input"],
    state: Readonly<LoopState>,
  ): Promise<Operations[K]["output"]> {
    this.state = { ...state };
    return (await this.operate(operation, args)) as Operations[K]["output"];
  }
  private async checkpoint(): Promise<void> {
    await this.legacy("checkpoint", {
      modelTurn: this.conversation.checkpoint(),
    });
  }
  private async warning(key: string, fallback: string): Promise<void> {
    await this.emit({
      type: "progress",
      content: this.input.copy[key] || fallback,
      metadata: { trace_kind: "warning" },
    });
  }
  private async release(discard = false): Promise<void> {
    if (!this.round) return;
    if (discard && this.input.deferOutput) {
      this.round.deferred.length = 0;
      await this.emit({
        type: "progress",
        content: "",
        metadata: { ...this.round.trace, call_role: "narration" },
      });
    } else
      for (const event of this.round.deferred.splice(0)) await this.emit(event);
  }
  private async call(
    settling: boolean,
    first: boolean,
    tools = this.tools,
  ): Promise<Round> {
    try {
      const round = await modelRound(
        this.input,
        this.conversation,
        tools.map((s) => s.schema),
        this.emit,
        this.signal,
        settling,
        first,
      );
      this.usage.push(round.usage);
      return round;
    } catch (error) {
      if (error instanceof ProviderFailure)
        throw new HostFailure(
          error.message,
          "native-provider",
          error.partialResponse,
        );
      throw error;
    }
  }
  private async policy(
    text: string,
    tools: string[] = [],
  ): Promise<JsonRecord> {
    if (!this.input.policyHooks)
      return { redirect: "", override: null, toolPolicy: "keep" };
    return record(await this.legacy("policy", { text, tools }));
  }
  private async finish(override: boolean): Promise<void> {
    if (!this.round) throw new Error("Missing model round");
    let text = override ? (this.override ?? "") : this.round.text.trim();
    if (override) {
      if (!this.input.deferOutput && this.round.text) {
        this.continued.push(this.round.text);
        if (text.includes(this.round.text))
          text = text.replace(this.round.text, "").trim();
        if (!this.round.toolCalls.length)
          this.conversation.appendAssistant(this.round);
      }
      await this.release(true);
      await this.legacy("publish_override", { text });
      this.conversation.messages.push({ role: "assistant", content: text });
    } else {
      await this.release();
      this.conversation.appendAssistant(this.round);
    }
    this.response = [...this.continued, text].filter(Boolean).join("\n\n");
    this.completed = true;
  }
  private async operate(
    operation: Operation,
    args: JsonRecord,
  ): Promise<unknown> {
    switch (operation) {
      case "prepare_recovery":
        return { available: false, rejected: false };
      case "begin_settlement":
        await this.warning(
          "budget_settling",
          "Exploration budget reached; settling the current task.",
        );
        this.conversation.appendInstruction(
          this.input.copy.settle ||
            "Finish the work already started. Use only the tools needed to settle the current task, then answer.",
        );
        return null;
      case "call_round": {
        if (this.input.userInputEnabled) {
          const raw = await this.legacy("read_user_inputs", {});
          const inputs = Array.isArray(raw) ? raw.map(record) : [];
          if (inputs.length) {
            const lead =
              this.input.copy.user_sent_while_working ||
              "[The user sent this while you were working. Take it into account from here on.]";
            this.conversation.appendInstruction(
              `${lead}\n${inputs.map((item) => String(item.content || "")).join("\n\n")}`,
            );
            await this.emit({
              type: "progress",
              content: "",
              metadata: {
                trace_kind: "user_input",
                user_inputs: inputs,
              },
            });
            await this.checkpoint();
          }
        }
        this.round = await this.call(
          args.settling === true,
          args.first === true,
        );
        const truncated = [
          "length",
          "max_tokens",
          "max_output_tokens",
        ].includes(this.round.finishReason);
        return {
          hasTools: this.round.toolCalls.length > 0,
          hasText: !!this.round.text.trim(),
          truncated,
          reasoningBudgetExhausted:
            truncated &&
            !this.round.text.trim() &&
            !!this.round.reasoning &&
            !this.round.toolCalls.length,
        };
      }
      case "continue_truncated":
        if (!this.round) throw new Error("Missing truncated round");
        await this.release();
        this.conversation.appendAssistant(this.round);
        if (this.round.text) this.continued.push(this.round.text);
        this.conversation.appendInstruction(
          this.round.text
            ? this.input.copy.continue_truncated ||
                "Continue where the response stopped, without repetition, and finish the answer."
            : this.input.copy.continue_reasoning ||
                "Your output budget was spent on reasoning. Act now: call a tool or write the answer without reconsidering the plan.",
        );
        await this.warning(
          "output_truncated",
          "The model reached its output limit; continuing.",
        );
        await this.checkpoint();
        return null;
      case "raise_reasoning_budget":
        throw new Error(
          "The model exhausted its reasoning output budget twice without an answer",
        );
      case "recover_empty":
        if (this.round?.reasoning)
          this.conversation.appendAssistant(this.round);
        this.conversation.appendInstruction(
          this.input.copy.empty_nudge ||
            "Your last round produced no answer or tool action. Execute a tool or write the answer now.",
        );
        return null;
      case "check_finish": {
        const policy = await this.policy(this.round?.text.trim() || "");
        this.redirect = String(policy.redirect || "");
        this.override =
          typeof policy.override === "string" ? policy.override : null;
        if (this.redirect) {
          if (!this.input.deferOutput && this.round?.text)
            this.continued.push(this.round.text);
          await this.release(true);
        }
        return { redirect: !!this.redirect, override: this.override !== null };
      }
      case "redirect_finish":
        if (this.round) this.conversation.appendAssistant(this.round);
        this.conversation.appendInstruction(this.redirect);
        return null;
      case "reject_finish":
        await this.warning(
          "finish_rejected",
          "The required capability action was not completed.",
        );
        this.response = this.continued.filter(Boolean).join("\n\n");
        this.completed = false;
        return null;
      case "finish":
        await this.finish(args.override === true);
        return null;
      case "dispatch_tools": {
        if (!this.round) throw new Error("Missing tool round");
        const policy = await this.policy(
          this.round.text,
          this.round.toolCalls.map((c) => c.name),
        );
        await this.release(policy.toolPolicy === "discard");
        this.conversation.appendAssistant(this.round);
        this.conversation.beginTools(this.round.toolCalls);
        await this.checkpoint();
        const previousLegacyCalls = this.dispatcher.legacyCalls;
        this.dispatch = await this.dispatcher.run(
          this.round.toolCalls,
          this.tools,
          this.state.tool_steps,
          ["length", "max_tokens", "max_output_tokens"].includes(
            this.round.finishReason,
          )
            ? "Model output was truncated. No tools in this batch were executed; retry with complete arguments."
            : "",
        );
        this.refreshHost =
          this.input.policyHooks ||
          this.dispatcher.legacyCalls !== previousLegacyCalls;
        this.usage.push(...(this.dispatch.usage || []));
        this.sources.push(...this.dispatch.sources);
        this.conversation.appendTools([], this.dispatch.modelMessages);
        await this.checkpoint();
        return { pause: this.dispatch.pause !== null };
      }
      case "resolve_pause": {
        if (!this.dispatch?.pause) throw new Error("Missing pause");
        const reply = record(
          await this.legacy("wait_for_reply", { dispatch: this.dispatch }),
        );
        if (reply.resumed === true && typeof reply.content === "string")
          this.conversation.resolveTool(
            this.dispatch.pause.callId,
            reply.content,
          );
        await this.checkpoint();
        return reply.resumed === true;
      }
      case "after_tools": {
        if (!this.refreshHost)
          return { override: false, terminate: !!this.dispatch?.terminate };
        const update = record(
          await this.legacy("after_tools", {
            metadataById: this.dispatch?.metadataById || {},
          }),
        );
        if (Array.isArray(update.tools))
          this.tools = update.tools as ToolSpec[];
        if (update.toolRuntime)
          this.input.toolRuntime = validateToolRuntime(update.toolRuntime);
        if (typeof update.checkpoint === "string" && update.checkpoint)
          this.conversation.foldCheckpoint(update.checkpoint);
        this.override =
          typeof update.override === "string" ? update.override : null;
        return {
          override: this.override !== null,
          terminate: !!this.dispatch?.terminate,
        };
      }
      case "terminate": {
        const value = this.dispatch?.terminate;
        if (!value) throw new Error("Missing terminal tool");
        await this.legacy("publish_terminator", { value });
        this.response = [...this.continued, value.content]
          .filter(Boolean)
          .join("\n\n");
        this.completed = true;
        this.conversation.messages.push({
          role: "assistant",
          content: this.response,
        });
        return null;
      }
      case "forced_finish": {
        this.conversation.appendInstruction(
          this.input.copy.finish ||
            "The tool budget is exhausted. Write the final answer using available evidence; do not call tools.",
        );
        this.round = await this.call(true, false, []);
        if (this.round.toolCalls.length)
          throw new Error(
            "Provider emitted tools after tool execution was disabled",
          );
        if (!this.round.text.trim())
          throw new Error("Model returned an empty final answer");
        if (
          ["length", "max_tokens", "max_output_tokens"].includes(
            this.round.finishReason,
          )
        )
          throw new Error("Final answer exceeded the output budget");
        const policy = await this.policy(this.round.text);
        if (policy.redirect) {
          await this.release(true);
          this.response = [
            ...this.continued,
            this.input.deferOutput ? "" : this.round.text,
          ]
            .filter(Boolean)
            .join("\n\n");
          this.completed = false;
          return { extraRounds: 1 };
        }
        this.override =
          typeof policy.override === "string" ? policy.override : null;
        await this.finish(this.override !== null);
        return { extraRounds: 1 };
      }
    }
  }
}

export async function runNative(
  value: unknown,
  legacy: LegacyPort,
  signal: AbortSignal,
): Promise<NativeResult> {
  const input = validateNativeInput(value);
  const events = new EventCoalescer(async (event) => {
    await legacy("event", { event });
  });
  try {
    const result = await new NativeSession(
      input,
      legacy,
      events.emit,
      signal,
    ).run();
    await events.flush();
    return result;
  } catch (error) {
    // Do not mask the original provider/cancellation failure with a closed host.
    if (!signal.aborted) await events.flush().catch(() => {});
    throw error;
  } finally {
    events.discard();
  }
}
