/** Bounded body reads share the same cancellation/idle policy as SSE. */
export async function readBody(
  body: ReadableStream<Uint8Array> | null,
  signal: AbortSignal,
  limit: number,
  idleMs = 90_000,
): Promise<string> {
  if (!body) return "";
  const reader = body.getReader(),
    decoder = new TextDecoder("utf-8", { fatal: true });
  const chunks: string[] = [];
  let bytes = 0;
  const cancel = () => {
    void reader.cancel(signal.reason).catch(() => {});
  };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    while (true) {
      signal.throwIfAborted();
      let timer: ReturnType<typeof setTimeout> | undefined;
      const part = await Promise.race([
        reader.read(),
        new Promise<never>((_, reject) => {
          timer = setTimeout(
            () => reject(new Error("Provider body idle timeout")),
            idleMs,
          );
        }),
      ]).finally(() => clearTimeout(timer));
      signal.throwIfAborted();
      if (part.done) break;
      bytes += part.value.byteLength;
      if (bytes > limit) throw new Error("Provider body exceeds limit");
      chunks.push(decoder.decode(part.value, { stream: true }));
    }
    chunks.push(decoder.decode());
    return chunks.join("");
  } finally {
    signal.removeEventListener("abort", cancel);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
