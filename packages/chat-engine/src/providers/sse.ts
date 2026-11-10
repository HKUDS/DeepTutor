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
    eventBytes = 0,
    skipLF = false;
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
      // CR, LF and CRLF each terminate one line. Consume CR immediately so
      // a CR-only server need not send another chunk before dispatch; suppress
      // only the optional LF, even when it arrives in a later read.
      let start = 0;
      if (skipLF && pending.length) {
        if (pending.startsWith("\n")) start = 1;
        skipLF = false;
      }
      const endings = /[\r\n]/g;
      endings.lastIndex = start;
      let ending: RegExpExecArray | null;
      while ((ending = endings.exec(pending)) !== null) {
        const line = pending.slice(start, ending.index);
        start = ending.index + 1;
        if (ending[0] === "\r") {
          if (pending[start] === "\n") {
            start++;
            endings.lastIndex = start;
          } else if (start === pending.length) skipLF = true;
        }
        if (line.length > 4_194_304)
          throw new Error("Provider SSE line exceeds limit");
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
      pending = pending.slice(start);
      if (pending.length > 4_194_304)
        throw new Error("Provider SSE line exceeds limit");
      if (part.done) {
        if (pending.startsWith("data:")) {
          const value = pending.slice(5).replace(/^ /, "");
          eventBytes += value.length;
          if (eventBytes > 4_194_304)
            throw new Error("Provider SSE event exceeds limit");
          data.push(value);
        }
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
