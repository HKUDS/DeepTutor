import type { Message, ProviderConfig } from "../native/types.js";
import { complete } from "./chat-completions.js";
import { ThinkFilter } from "./think-filter.js";

export function visibleText(text: string): string {
  const filter = new ThinkFilter();
  return filter
    .feed(text, true)
    .filter(([kind]) => kind === "content")
    .map(([, value]) => value)
    .join("");
}

/** Small application calls (session titles), sharing provider limits and HTTP. */
export async function oneShot(
  input: { provider: ProviderConfig; messages: Message[] },
  signal: AbortSignal,
) {
  const result = await complete(
    input.provider,
    input.messages,
    [],
    null,
    signal,
    async () => {},
  );
  if (result.calls.length)
    throw new Error("Model emitted tools in a tool-free request");
  return { ...result, text: visibleText(result.text) };
}
