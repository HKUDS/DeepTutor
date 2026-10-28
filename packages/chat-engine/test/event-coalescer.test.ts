import { test } from "node:test";
import assert from "node:assert/strict";
import { EventCoalescer } from "../src/native/event-coalescer.js";
import type { EngineEvent } from "../src/native/types.js";
const delta = (content: string, type = "content", id = "one"): EngineEvent => ({
  type,
  content,
  metadata: { call_id: id },
});

test("first token is immediate; large bursts are bounded and text/order are lossless", async () => {
  const received: EngineEvent[] = [];
  const coalescer = new EventCoalescer(
    async (e) => {
      received.push(e);
    },
    24,
    1024,
  );
  await coalescer.emit(delta("first"));
  assert.equal(received[0]?.content, "first");
  for (let i = 0; i < 10000; i++) await coalescer.emit(delta("x"));
  await coalescer.emit(delta("done", "progress"));
  await coalescer.flush();
  assert.equal(
    received.map((e) => e.content).join(""),
    "first" + "x".repeat(10000) + "done",
  );
  assert.ok(received.length < 30);
  assert.ok(received.every((e) => e.content.length <= 1024));
  assert.equal(received.at(-1)?.type, "progress");
});
test("trace and thinking boundaries never merge; a stalled provider flushes its final delta", async () => {
  const received: EngineEvent[] = [];
  const coalescer = new EventCoalescer(async (e) => {
    received.push(e);
  }, 5);
  await coalescer.emit(delta("a"));
  await coalescer.emit(delta("b"));
  await coalescer.emit(delta("think", "thinking"));
  await coalescer.emit(delta("c", "content", "two"));
  await coalescer.emit(delta("d", "content", "two"));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.deepEqual(
    received.map((e) => [e.type, e.content]),
    [
      ["content", "a"],
      ["content", "b"],
      ["thinking", "think"],
      ["content", "c"],
      ["content", "d"],
    ],
  );
  await coalescer.flush();
});
test("sink failures propagate and buffered data is released on cancellation", async () => {
  let count = 0;
  const coalescer = new EventCoalescer(async () => {
    if (++count > 1) throw new Error("closed host");
  }, 1);
  await coalescer.emit(delta("first"));
  await coalescer.emit(delta("pending"));
  await new Promise((resolve) => setTimeout(resolve, 10));
  await assert.rejects(coalescer.flush(), /closed host/);
  coalescer.discard();
});

test("slow provider deltas bypass buffering after the cadence window", async () => {
  const received: EngineEvent[] = [];
  const coalescer = new EventCoalescer(async (e) => {
    received.push(e);
  }, 2);
  await coalescer.emit(delta("first"));
  await new Promise((resolve) => setTimeout(resolve, 8));
  await coalescer.emit(delta("slow"));
  assert.equal(received.length, 2);
  await coalescer.flush();
});
