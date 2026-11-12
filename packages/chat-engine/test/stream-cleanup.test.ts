import { test } from "node:test";
import assert from "node:assert/strict";
import { readBody } from "../src/providers/body.js";
import { sse } from "../src/providers/sse.js";
import { withProviderLimit } from "../src/providers/limits.js";
import type { ProviderConfig } from "../src/native/types.js";

function fixture(text?: string) {
  let finish!: () => void;
  let calls = 0;
  const cancelled = new Promise<void>((resolve) => {
    finish = resolve;
  });
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      if (text !== undefined)
        controller.enqueue(new TextEncoder().encode(text));
    },
    cancel() {
      calls++;
      return cancelled;
    },
  });
  return { body, finish, calls: () => calls };
}

async function settles(pending: Promise<unknown>) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      pending.then(
        () => "resolved",
        () => "rejected",
      ),
      new Promise<string>((resolve) => {
        timer = setTimeout(() => resolve("waiting"), 100);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

for (const kind of [
  "body-timeout",
  "body-limit",
  "sse-timeout",
  "sse-return",
] as const) {
  test(`${kind} settles and releases its reader when source cancellation stalls`, async () => {
    const f = fixture(
      kind === "body-limit"
        ? "too large"
        : kind === "sse-return"
          ? "data: ready\n\n"
          : undefined,
    );
    const abort = new AbortController();
    let pending: Promise<unknown>;
    if (kind.startsWith("body")) pending = readBody(f.body, abort.signal, 1, 5);
    else {
      const events = sse(f.body, abort.signal, 5);
      if (kind === "sse-return") {
        assert.equal((await events.next()).value, "ready");
        pending = events.return(undefined);
      } else pending = events.next();
    }
    try {
      assert.equal(
        await settles(pending),
        kind === "sse-return" ? "resolved" : "rejected",
      );
      assert.equal(f.calls(), 1);
      assert.equal(f.body.locked, false);
      if (kind !== "sse-return")
        await assert.rejects(
          pending,
          kind.endsWith("limit") ? /exceeds/ : /timeout/,
        );
    } finally {
      f.finish();
      await pending.catch(() => {});
    }
  });
}

test("a timed-out body releases admission before source cancellation completes", async () => {
  const f = fixture();
  const config: ProviderConfig = {
    endpoint: "http://cleanup-fixture",
    apiKey: "",
    model: "fixture",
    headers: {},
    format: "chat_completions",
    completion: {},
    stream: true,
    maxConcurrency: 1,
    requestsPerMinute: 600,
  };
  const signal = new AbortController().signal;
  const first = withProviderLimit(config, signal, () =>
    readBody(f.body, signal, 100, 5),
  );
  const second = withProviderLimit(config, signal, async () => "next turn");
  try {
    assert.equal(await settles(first), "rejected");
    assert.equal(await second, "next turn");
  } finally {
    f.finish();
    await first.catch(() => {});
    await second;
  }
});
