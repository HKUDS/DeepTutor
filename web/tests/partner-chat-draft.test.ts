import test from "node:test";
import assert from "node:assert/strict";
import type { StreamEvent } from "../features/chat/model/protocol";
import { createPartnerDraftPublisher } from "../lib/partner-chat-draft";

function createFrameQueue() {
  const frames: Array<{ callback: () => void; cancelled: boolean }> = [];
  return {
    frames,
    scheduler: {
      schedule: (callback: () => void) => {
        const frame = { callback, cancelled: false };
        frames.push(frame);
        return frames.length - 1;
      },
      cancel: (handle: number) => {
        frames[handle].cancelled = true;
      },
    },
    flush(index = 0) {
      const frame = frames[index];
      assert.ok(frame);
      assert.equal(frame.cancelled, false);
      frame.callback();
    },
  };
}

test("partner draft snapshots coalesce bursts into one frame update", () => {
  const queue = createFrameQueue();
  const published: Array<{ events: StreamEvent[]; content: string } | null> =
    [];
  let live: { events: StreamEvent[]; content: string } | null = {
    events: [],
    content: "",
  };
  const publisher = createPartnerDraftPublisher(
    () => live,
    (draft) => published.push(draft),
    queue.scheduler,
  );

  for (const token of ["a", "b", "c"]) {
    live.events.push({ type: "content", content: token } as StreamEvent);
    live.content += token;
    publisher.publish();
  }

  assert.equal(queue.frames.length, 1);
  assert.equal(published.length, 0);
  queue.flush();
  assert.equal(published.length, 1);
  assert.equal(published[0]?.content, "abc");
  assert.equal(published[0]?.events.length, 3);
});

test("canceling a partner draft frame prevents a stale publish", () => {
  const queue = createFrameQueue();
  const published: unknown[] = [];
  let live: { events: StreamEvent[]; content: string } | null = {
    events: [],
    content: "partial",
  };
  const publisher = createPartnerDraftPublisher(
    () => live,
    (draft) => published.push(draft),
    queue.scheduler,
  );

  publisher.publish();
  publisher.cancel();
  live = null;

  assert.equal(queue.frames[0].cancelled, true);
  assert.equal(published.length, 0);
});

test("terminal partner updates replace a scheduled frame immediately", () => {
  const queue = createFrameQueue();
  const published: Array<{ events: StreamEvent[]; content: string } | null> =
    [];
  let live: { events: StreamEvent[]; content: string } | null = {
    events: [],
    content: "partial",
  };
  const publisher = createPartnerDraftPublisher(
    () => live,
    (draft) => published.push(draft),
    queue.scheduler,
  );

  publisher.publish();
  live = null;
  publisher.publishNow();

  assert.equal(queue.frames[0].cancelled, true);
  assert.deepEqual(published, [null]);
});
