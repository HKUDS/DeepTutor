/** Stateless service completions share transport/limits with the agent loop. */
import { record, validateProvider } from "../native/types.js";
import type { LegacyPort, Message } from "../native/types.js";
import { complete } from "./chat-completions.js";
import { EventCoalescer } from "../native/event-coalescer.js";

export async function serviceCall(
  value: unknown,
  port: LegacyPort,
  signal: AbortSignal,
) {
  const input = record(value);
  const provider = validateProvider(input.provider);
  if (
    !Array.isArray(input.messages) ||
    input.messages.some((m) => {
      const message = record(m);
      return (
        !["system", "developer", "user", "assistant"].includes(
          String(message.role),
        ) || typeof message.content !== "string"
      );
    })
  )
    throw new Error("Invalid text service messages");
  const events = new EventCoalescer(async (event) => {
    await port("event", { event });
  });
  try {
    const result = await complete(
      provider,
      input.messages as Message[],
      [],
      null,
      signal,
      async (kind, text) => {
        if (kind === "tool_arguments")
          throw new Error("Unexpected service tool call");
        if (input.emit === true)
          await events.emit({ type: kind, content: text, metadata: {} });
      },
    );
    if (result.calls.length) throw new Error("Unexpected service tool call");
    await events.flush();
    return result;
  } catch (error) {
    if (!signal.aborted) await events.flush().catch(() => {});
    throw error;
  } finally {
    events.discard();
  }
}
