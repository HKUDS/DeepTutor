import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  ReconnectingWebSocket,
  reconnectDelayMs,
} from "../lib/reconnecting-websocket";

class FakeSocket {
  readyState = 0;
  sent: string[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  open(): void {
    this.readyState = 1;
    this.onopen?.({} as Event);
  }

  drop(): void {
    this.readyState = 3;
    this.onclose?.({} as CloseEvent);
  }

  close(): void {
    if (this.readyState !== 3) this.drop();
  }

  send(payload: string): void {
    this.sent.push(payload);
  }
}

function createHarness(shouldReconnect: () => boolean = () => true) {
  const sockets: FakeSocket[] = [];
  const scheduled: Array<{
    callback: () => void;
    delayMs: number;
    cancelled: boolean;
  }> = [];
  let now = 0;
  const client = new ReconnectingWebSocket(
    "ws://partner.test",
    { onMessage: () => {} },
    {
      createSocket: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      shouldReconnect,
      now: () => now,
      scheduler: {
        set: (callback, delayMs) => {
          const task = { callback, delayMs, cancelled: false };
          scheduled.push(task);
          return task;
        },
        clear: (handle) => {
          (handle as (typeof scheduled)[number]).cancelled = true;
        },
      },
    },
  );
  return {
    client,
    sockets,
    scheduled,
    setNow: (value: number) => {
      now = value;
    },
  };
}

test("reconnect delay grows exponentially and remains bounded", () => {
  assert.deepEqual(
    [0, 1, 2, 3, 8].map((attempt) => reconnectDelayMs(attempt, 250, 2_000)),
    [250, 500, 1_000, 2_000, 2_000],
  );
});

test("unexpected closes reconnect without creating concurrent sockets", () => {
  const { client, sockets, scheduled } = createHarness();
  client.start();
  client.start();
  assert.equal(sockets.length, 1);

  sockets[0].open();
  sockets[0].drop();
  assert.equal(scheduled[0].delayMs, 250);

  scheduled[0].callback();
  assert.equal(sockets.length, 2);
  sockets[1].drop();
  assert.equal(scheduled[1].delayMs, 500);
});

test("wake reconnects immediately when a hidden page becomes active", () => {
  let active = true;
  const { client, sockets, scheduled } = createHarness(() => active);
  client.start();
  sockets[0].open();
  active = false;
  sockets[0].drop();
  assert.equal(
    scheduled.length,
    0,
    "hidden pages should not spin retry timers",
  );

  active = true;
  client.wake();
  assert.equal(sockets.length, 2);
});

test("a retry timer that fires in the background waits for wake", () => {
  let active = true;
  const { client, sockets, scheduled } = createHarness(() => active);
  client.start();
  sockets[0].open();
  sockets[0].drop();

  active = false;
  scheduled[0].callback();
  assert.equal(sockets.length, 1);

  active = true;
  client.wake();
  assert.equal(sockets.length, 2);
});

test("wake replaces only a stale connecting socket", () => {
  const { client, sockets, setNow } = createHarness();
  client.start();
  setNow(9_999);
  client.wake();
  assert.equal(sockets.length, 1);

  setNow(10_001);
  client.wake();
  assert.equal(sockets.length, 2);
  assert.equal(sockets[0].readyState, 3);
});

test("stop cancels pending retries and closes without reconnecting", () => {
  const { client, sockets, scheduled } = createHarness();
  client.start();
  sockets[0].open();
  sockets[0].drop();
  client.stop();

  assert.equal(scheduled[0].cancelled, true);
  scheduled[0].callback();
  assert.equal(sockets.length, 1);
});

test("partner composer restores focus after streaming and page return", () => {
  const source = readFileSync(
    path.resolve(process.cwd(), "components/partners/PartnerComposer.tsx"),
    "utf8",
  );

  assert.match(source, /restoreFocusAfterSendRef\.current = true/);
  assert.match(source, /if \(disabled \|\| streaming/);
  assert.match(source, /window\.addEventListener\("blur", rememberFocus\)/);
  assert.match(
    source,
    /document\.addEventListener\("visibilitychange", restoreFocus\)/,
  );
});
