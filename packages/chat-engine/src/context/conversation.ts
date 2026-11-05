import type {
  ContextSeed,
  JsonRecord,
  Message,
  Round,
  ToolSchema,
} from "../native/types.js";

const SNIPPED =
  "[Earlier tool result omitted from this request to fit the context window; call the tool again if needed.]";
export function estimateText(text: string): number {
  // Explicitly approximate: avoid loading a large tokenizer into either runtime.
  // Provider-reported usage remains the authoritative billing count.
  let ascii = 0,
    other = 0;
  for (const char of text) {
    if (char.codePointAt(0)! < 128) ascii++;
    else other++;
  }
  return Math.ceil(ascii / 3 + other * 2);
}
export function estimateValue(value: unknown): number {
  if (typeof value === "string") return estimateText(value);
  if (Array.isArray(value))
    return value.reduce((sum, x) => sum + estimateValue(x), 0);
  if (value && typeof value === "object") {
    const x = value as JsonRecord;
    if (["image_url", "input_image", "image"].includes(String(x.type)))
      return 4096;
    return Object.entries(x).reduce(
      (sum, [key, v]) => sum + estimateText(key) + estimateValue(v),
      0,
    );
  }
  return value == null ? 0 : 1;
}
const estimate = estimateValue;

export class Conversation {
  readonly messages: Message[];
  readonly turnStart: number;
  private lastBudget: JsonRecord = {};
  private lastTools: ToolSchema[] = [];
  private transient: { after: number; messages: Message[] }[] = [];
  private projectionBoundary: number;
  private exclusions: [number, number][] = [];
  constructor(readonly seed: ContextSeed) {
    this.messages = [{ role: "system", content: seed.system }, ...seed.history];
    this.turnStart = this.messages.length;
    const prior = new Map<string, unknown>();
    for (const message of this.messages)
      if (typeof message._context_snapshot === "string")
        prior.set(message._context_snapshot, message.content);
    const snapshots = { ...seed.snapshots };
    for (const name of [...prior.keys()].sort()) {
      if (!(name in snapshots))
        snapshots[name] =
          `[Runtime context: ${name}]\nThis section is now empty; earlier values no longer apply.`;
    }
    for (const [name, value] of Object.entries(snapshots)) {
      if (prior.get(name) !== value)
        this.messages.push({
          role: "user",
          content: value,
          _context_snapshot: name,
        });
    }
    this.messages.push(structuredClone(seed.user));
    this.projectionBoundary = this.messages.length;
  }

  appendInstruction(text: string): void {
    const last = this.messages.at(-1);
    if (last?.role === "user" && typeof last.content === "string")
      last.content = `${last.content.trimEnd()}\n\n${text}`;
    else if (last?.role === "user" && Array.isArray(last.content)) {
      last.content = [...last.content, { type: "text", text }];
    } else this.messages.push({ role: "user", content: text });
  }

  appendAssistant(round: Round): void {
    const message: Message = { role: "assistant", content: round.text || null };
    if (round.toolCalls.length)
      message.tool_calls = round.toolCalls.map((c) => ({
        id: c.id,
        type: "function",
        function: { name: c.name, arguments: c.arguments },
      }));
    if (round.reasoning) {
      message.reasoning_content = round.reasoning;
      message._provider_response_state = { reasoning_content: round.reasoning };
    }
    this.messages.push(message);
  }

  beginTools(calls: { id: string; name: string }[]): void {
    this.messages.push(
      ...calls.map((call, index) => ({
        role: "tool",
        tool_call_id: call.id,
        name: call.name,
        content:
          index >= 15
            ? "Tool call not executed: this round is limited to 15 calls."
            : "[Tool result unavailable: execution was interrupted. Do not assume the side effect failed.]",
      })),
    );
  }

  appendTools(messages: Message[], transient: Message[]): void {
    this.messages.push(...messages);
    if (transient.length)
      this.transient.push({ after: this.messages.length, messages: transient });
  }
  resolveTool(callId: string, content: string): void {
    const message = [...this.messages]
      .reverse()
      .find((m) => m.role === "tool" && m.tool_call_id === callId);
    if (!message) throw new Error("Paused tool result is missing");
    message.content = content;
  }
  foldCheckpoint(summary: string): void {
    // Compact only request projection. The durable turn retains every effect,
    // including completed tool results before the checkpoint.
    this.exclusions.push([this.projectionBoundary, this.messages.length]);
    this.messages.push({
      role: "system",
      content: `[Context checkpoint]\n${summary}`,
    });
    this.projectionBoundary = this.messages.length;
  }

  project(tools: ToolSchema[]): { messages: Message[]; snipped: boolean } {
    const seenImages = new Set<string>();
    const working: Message[] = [];
    for (const [index, message] of this.messages.entries()) {
      if (this.exclusions.some(([start, end]) => index >= start && index < end))
        continue;
      working.push(message);
      for (const image of this.transient)
        if (image.after === index + 1) working.push(...image.messages);
    }
    // History is immutable; projection only changes message envelopes/content
    // arrays. Share large text/image strings instead of cloning the full graph.
    const messages = working.map((original) => {
      const m = { ...original };
      delete m._context_snapshot;
      const state = m._provider_response_state as JsonRecord | undefined;
      if (
        m.role === "assistant" &&
        state?.reasoning_content &&
        !m.reasoning_content
      )
        m.reasoning_content = state.reasoning_content;
      delete m._provider_response_state;
      if (Array.isArray(m.content))
        m.content = m.content.map((raw: JsonRecord) => {
          if (raw.type !== "image_url") return raw;
          const url = String(
            (raw.image_url as JsonRecord | undefined)?.url ?? "",
          );
          if (!url) return raw;
          if (seenImages.has(url))
            return {
              type: "text",
              text: "[Image already supplied earlier in this conversation.]",
            };
          seenImages.add(url);
          return raw;
        });
      return m;
    });
    const toolTokens = estimate(tools);
    const limit = Math.max(
      1,
      Math.floor(this.seed.contextWindow * 0.9) -
        this.seed.outputTokens -
        toolTokens,
    );
    let total = estimate(messages),
      snipped = false;
    for (const message of messages) {
      if (total <= limit) break;
      if (message.role !== "tool" || message.content === SNIPPED) continue;
      const old = estimate(message);
      message.content = SNIPPED;
      total += estimate(message) - old;
      snipped = true;
    }
    // Remove only complete older user turns; never orphan a tool result or
    // remove this turn's request, snapshots, or assistant/tool exchange.
    let remainingHistory = this.turnStart - 1;
    while (total > limit && remainingHistory > 0) {
      let end = 2;
      while (end <= remainingHistory && messages[end]?.role !== "user") end++;
      const removed = messages.splice(1, Math.min(end - 1, remainingHistory));
      total -= estimate(removed);
      remainingHistory -= removed.length;
      snipped = true;
    }
    if (total > limit)
      throw new Error(
        "Current turn exceeds the configured context window; shorten input or increase the context limit",
      );
    const systemTokens = estimate(messages.filter((m) => m.role === "system"));
    this.lastTools = tools;
    this.lastBudget = {
      window: this.seed.contextWindow,
      window_estimated: true,
      used_tokens: total + toolTokens,
      free_tokens: Math.max(0, this.seed.contextWindow - total - toolTokens),
      model: this.seed.model,
      counter: "character_estimate",
      deferred_tool_count: 0,
      segments: [
        { key: "system_prompt", tokens: systemTokens },
        { key: "messages", tokens: total - systemTokens },
        { key: "tool_schemas", tokens: toolTokens },
      ],
    };
    return { messages, snipped };
  }
  budget(): JsonRecord {
    return this.lastBudget;
  }
  checkpoint(): JsonRecord {
    const messages = structuredClone(this.messages.slice(this.turnStart));
    // Record a coherent replay even when the process dies during a tool batch.
    const answered = new Set(
      messages.filter((m) => m.role === "tool").map((m) => m.tool_call_id),
    );
    const complete: Message[] = [];
    for (const message of messages) {
      complete.push(message);
      for (const call of (message.tool_calls ?? []) as JsonRecord[]) {
        if (!answered.has(call.id))
          complete.push({
            role: "tool",
            tool_call_id: call.id,
            content:
              "[Tool result unavailable: execution was interrupted. Do not assume the side effect failed.]",
          });
      }
    }
    return {
      version: 1,
      messages: complete,
      system: this.seed.system,
      tools: this.lastTools,
      route: this.seed.route,
    };
  }
}
