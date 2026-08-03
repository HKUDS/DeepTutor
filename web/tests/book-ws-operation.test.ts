import test from "node:test";
import assert from "node:assert/strict";

import {
  runBookSocketOperation,
  type BookSocketLike,
  type BookWsEvent,
} from "../lib/book-ws-operation";

class FakeBookSocket implements BookSocketLike {
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  sent: string[] = [];
  closeCalls = 0;

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.closeCalls += 1;
  }

  open(): void {
    this.onopen?.(new Event("open"));
  }

  message(event: BookWsEvent): void {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent<string>);
  }

  fail(): void {
    this.onerror?.(new Event("error"));
  }

  disconnect(): void {
    this.onclose?.({ code: 1006, reason: "network reset" } as CloseEvent);
  }
}

test("long-running book operation stays pending through progress and resolves on its result event", async () => {
  const socket = new FakeBookSocket();
  const progress: string[] = [];
  const operation = runBookSocketOperation<{
    type: string;
    book: { id: string };
  }>(() => socket, {
    message: {
      type: "confirm_proposal",
      book_id: "book-1",
      proposal: { title: "Test" },
    },
    resultType: "confirm_proposal_result",
    onEvent: (event) => progress.push(event.type),
  });

  socket.open();
  assert.deepEqual(JSON.parse(socket.sent[0]), {
    type: "confirm_proposal",
    book_id: "book-1",
    proposal: { title: "Test" },
  });

  socket.message({ type: "stage_start", stage: "spine" });
  socket.message({ type: "content", content: "working" });
  assert.equal(socket.closeCalls, 0);

  socket.message({
    type: "confirm_proposal_result",
    book: { id: "book-1" },
  });

  const result = await operation;
  assert.equal(result.book.id, "book-1");
  assert.deepEqual(progress, [
    "stage_start",
    "content",
    "confirm_proposal_result",
  ]);
  assert.equal(socket.closeCalls, 1);
});

test("book operation rejects backend error frames and closes its socket", async () => {
  const socket = new FakeBookSocket();
  const operation = runBookSocketOperation(() => socket, {
    message: { type: "compile_page", book_id: "book-1", page_id: "page-1" },
    resultType: "compile_page_result",
  });

  socket.open();
  socket.message({ type: "error", content: "provider unavailable" });

  await assert.rejects(operation, /provider unavailable/);
  assert.equal(socket.closeCalls, 1);
});

test("book operation rejects when the socket closes before a result", async () => {
  const socket = new FakeBookSocket();
  const operation = runBookSocketOperation(() => socket, {
    message: { type: "compile_page", book_id: "book-1", page_id: "page-1" },
    resultType: "compile_page_result",
  });

  socket.open();
  socket.disconnect();

  await assert.rejects(operation, /closed before compile_page_result/);
  assert.equal(socket.closeCalls, 0);
});
