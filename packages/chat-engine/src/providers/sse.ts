/** Incremental UTF-8 SSE parsing with bounded buffering and per-read idle timeout. */
export async function* sse(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
  idleMs = 90_000,
): AsyncGenerator<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let pending = "",
    data: string[] = [],
    eventBytes = 0;
  const aborted = () => {
    void reader.cancel(signal.reason).catch(() => {});
  };
  signal.addEventListener("abort", aborted, { once: true });
  try {
    while (true) {
      signal.throwIfAborted();
      let timer: ReturnType<typeof setTimeout> | undefined;
      let part: ReadableStreamReadResult<Uint8Array>;
      try {
        part = await Promise.race([
          reader.read(),
          new Promise<never>((_, reject) => {
            timer = setTimeout(
              () => reject(new Error("Provider stream idle timeout")),
              idleMs,
            );
          }),
        ]);
      } finally {
        clearTimeout(timer);
      }
      signal.throwIfAborted();
      pending += part.done
        ? decoder.decode()
        : decoder.decode(part.value, { stream: true });
      if (pending.length > 4_194_304)
        throw new Error("Provider SSE line exceeds limit");
      // CRLF is normalized only after a complete line, including split CR/LF.
      let end: number;
      while ((end = pending.indexOf("\n")) >= 0) {
        const line = pending.slice(0, end).replace(/\r$/, "");
        pending = pending.slice(end + 1);
        if (!line) {
          if (data.length) yield data.join("\n");
          data = [];
          eventBytes = 0;
        } else if (line.startsWith("data:")) {
          const value = line.slice(5).replace(/^ /, "");
          eventBytes += value.length;
          if (eventBytes > 4_194_304)
            throw new Error("Provider SSE event exceeds limit");
          data.push(value);
        }
      }
      if (part.done) {
        if (pending.startsWith("data:"))
          data.push(pending.slice(5).replace(/^ /, ""));
        if (data.length) yield data.join("\n");
        break;
      }
    }
  } finally {
    signal.removeEventListener("abort", aborted);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
