import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCancelTurn,
  buildSubmitUserReply,
} from "../contracts/parse/turn-command";
import {
  TurnRuntimeClient,
  type RuntimeScheduler,
} from "../features/chat/transport/TurnRuntimeClient";
import {
  SOCKET_CONNECTING,
  SOCKET_OPEN,
  type TurnSocket,
} from "../features/chat/transport/socket";

class FakeSocket implements TurnSocket {
  readyState = SOCKET_CONNECTING;
  sent: Record<string, unknown>[] = [];
  private listeners = new Map<
    string,
    Array<(event: { data: unknown }) => void>
  >();

  addEventListener(
    type: string,
    listener: (event: { data: unknown }) => void,
  ): void {
    const rows = this.listeners.get(type) ?? [];
    rows.push(listener);
    this.listeners.set(type, rows);
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }

  close(): void {
    this.readyState = 3;
    this.emit("close");
  }

  open(): void {
    this.readyState = SOCKET_OPEN;
    this.emit("open");
  }

  message(value: unknown): void {
    this.emit("message", {
      data: typeof value === "string" ? value : JSON.stringify(value),
    });
  }

  private emit(
    type: string,
    event: { data: unknown } = { data: undefined },
  ): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

class FakeScheduler implements RuntimeScheduler {
  tasks: Array<() => void> = [];
  setTimeout(callback: () => void): unknown {
    this.tasks.push(callback);
    return callback;
  }
  clearTimeout(handle: unknown): void {
    this.tasks = this.tasks.filter((task) => task !== handle);
  }
  runNext(): void {
    this.tasks.shift()?.();
  }
}

function stream(seq: number, type = "content"): Record<string, unknown> {
  return {
    type,
    turn_id: "turn-1",
    session_id: "session-1",
    seq,
    timestamp: seq,
    content: `token-${seq}`,
    metadata: {},
    protocol_version: "2.0",
  };
}

function harness() {
  const sockets: FakeSocket[] = [];
  const scheduler = new FakeScheduler();
  const events: Array<{ type?: string; seq?: number }> = [];
  const states: string[] = [];
  const diagnostics: string[] = [];
  const reconciliations: unknown[] = [];
  const client = new TurnRuntimeClient({
    socketFactory: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    scheduler,
    random: () => 0.5,
    maxBufferedGap: 3,
    replayProbeDelayMs: 5_000,
    onEvent: (event) => events.push(event),
    onStateChange: (state) => states.push(state),
    onDiagnostic: (value) => diagnostics.push(value),
    onReconcile: (cursor) => reconciliations.push(cursor),
  });
  return {
    client,
    diagnostics,
    events,
    reconciliations,
    scheduler,
    sockets,
    states,
  };
}

test("reconnect resumes from the persisted cursor through a different worker", () => {
  const { client, scheduler, sockets, states } = harness();
  client.setResumeCursor("turn-1", 8);
  client.connect();
  sockets[0].open();
  assert.equal(sockets[0].sent[0].type, "resume_from");
  assert.equal(sockets[0].sent[0].seq, 8);

  sockets[0].close();
  assert.equal(states.at(-1), "recovering");
  scheduler.runNext();
  sockets[1].open();
  assert.equal(sockets[1].sent[0].seq, 8);
});

test("duplicates are dropped and bounded out-of-order events are restored", () => {
  const { client, events, scheduler, sockets } = harness();
  client.connect();
  sockets[0].open();
  sockets[0].message(stream(2));
  sockets[0].message(stream(1));
  sockets[0].message(stream(1));
  assert.deepEqual(
    events.map((event) => event.seq),
    [1, 2],
  );
  assert.equal(scheduler.tasks.length, 1);
});

test("large sequence gaps request reconciliation instead of emitting", () => {
  const { client, events, reconciliations, sockets } = harness();
  client.setResumeCursor("turn-1", 1);
  client.connect();
  sockets[0].open();
  sockets[0].message(stream(8));
  assert.equal(events.length, 0);
  assert.deepEqual(reconciliations, [{ turnId: "turn-1", afterSeq: 1 }]);
  assert.deepEqual(sockets[0].sent.at(-1), {
    type: "resume_from",
    turn_id: "turn-1",
    seq: 1,
    protocol_version: "2.0",
  });
});

test("a bounded missing frame triggers durable replay and releases buffered done", () => {
  const { client, events, reconciliations, scheduler, sockets } = harness();
  client.connect();
  sockets[0].open();
  sockets[0].message(stream(1));
  sockets[0].message(stream(3, "done"));

  assert.deepEqual(
    events.map((event) => event.seq),
    [1],
  );
  scheduler.runNext();
  assert.deepEqual(reconciliations, [{ turnId: "turn-1", afterSeq: 1 }]);
  assert.equal(sockets[0].sent.at(-1)?.type, "resume_from");
  assert.equal(sockets[0].sent.at(-1)?.seq, 1);

  sockets[0].message(stream(2, "stage_end"));
  assert.deepEqual(
    events.map((event) => event.seq),
    [1, 2, 3],
  );
  assert.equal(events.at(-1)?.type, "done");
  assert.equal(scheduler.tasks.length, 0);
});

test("an idle non-terminal stream probes durable replay for a missed done", () => {
  const { client, events, reconciliations, scheduler, sockets } = harness();
  client.connect();
  sockets[0].open();
  sockets[0].message(stream(1));

  assert.equal(scheduler.tasks.length, 1);
  scheduler.runNext();
  assert.deepEqual(reconciliations, [{ turnId: "turn-1", afterSeq: 1 }]);
  assert.equal(sockets[0].sent.at(-1)?.type, "resume_from");

  sockets[0].message(stream(2, "done"));
  assert.deepEqual(
    events.map((event) => event.type),
    ["content", "done"],
  );
  assert.equal(scheduler.tasks.length, 0);
});

test("a stale React resume cursor cannot rewind the live transport", () => {
  const { client } = harness();
  client.setResumeCursor("turn-1", 8);
  client.setResumeCursor("turn-1", 3);
  assert.deepEqual(client.cursor, { turnId: "turn-1", afterSeq: 8 });

  client.setResumeCursor("turn-2", 0);
  assert.deepEqual(client.cursor, { turnId: "turn-2", afterSeq: 0 });
});

test("heartbeats and invalid or future frames never become chat events", () => {
  const { client, diagnostics, events, sockets } = harness();
  client.connect();
  sockets[0].open();
  sockets[0].message({ type: "pong", protocol_version: "2.0" });
  sockets[0].message({ type: "future", content: "private" });
  sockets[0].message("not json");
  assert.equal(events.length, 0);
  assert.equal(diagnostics.length, 2);
  assert.doesNotMatch(diagnostics.join(" "), /private/);
});

test("mutations survive unrelated events and reconnects until their matching acknowledgement", () => {
  const { client, scheduler, sockets } = harness();
  client.setResumeCursor("turn-1", 2);
  client.connect();
  sockets[0].open();
  client.cancel(buildCancelTurn("turn-1", "cancel-1"));
  client.send(
    buildSubmitUserReply({
      turnId: "turn-1",
      text: "continue",
      commandId: "reply-1",
    }),
  );
  assert.equal(sockets[0].readyState, SOCKET_OPEN);

  sockets[0].close();
  scheduler.runNext();
  sockets[1].open();
  assert.equal(
    sockets[1].sent.filter((item) => item.type === "submit_user_reply").length,
    1,
  );
  sockets[1].message(stream(3));

  sockets[1].close();
  scheduler.runNext();
  sockets[2].open();
  assert.equal(
    sockets[2].sent.filter((item) => item.type === "submit_user_reply").length,
    1,
  );
  sockets[2].message({
    type: "command_ack",
    command_id: "reply-1",
    command_type: "submit_user_reply",
    accepted: true,
    turn_id: "turn-1",
    error_code: "",
    message: "",
    protocol_version: "2.0",
  });

  sockets[2].close();
  scheduler.runNext();
  sockets[3].open();
  assert.equal(
    sockets[3].sent.filter((item) => item.type === "submit_user_reply").length,
    0,
  );
  assert.equal(
    sockets[3].sent.filter((item) => item.type === "cancel_turn").length,
    1,
  );
  sockets[3].message({
    type: "command_ack",
    command_id: "cancel-1",
    command_type: "cancel_turn",
    accepted: false,
    turn_id: "turn-1",
    error_code: "turn_not_active",
    message: "already terminal",
    protocol_version: "2.0",
  });

  sockets[3].close();
  scheduler.runNext();
  sockets[4].open();
  assert.equal(
    sockets[4].sent.filter((item) => item.type === "cancel_turn").length,
    0,
  );
});

test("stopping cancels retries and idle hidden sessions do not reconnect", () => {
  const { client, scheduler, sockets } = harness();
  client.connect();
  sockets[0].open();
  client.setPageVisible(false);
  sockets[0].close();
  assert.equal(scheduler.tasks.length, 0);

  client.setPageVisible(true);
  assert.equal(sockets.length, 2);
  client.stop();
  assert.equal(client.state, "stopped");
  assert.equal(scheduler.tasks.length, 0);
});

test("a rejected reply resolves its waiter instead of leaving the card pending", async () => {
  const { client, sockets } = harness();
  client.connect();
  sockets[0].open();

  const verdict = client.sendAwaitingAck(
    buildSubmitUserReply({
      turnId: "turn-1",
      text: "B",
      commandId: "reply-1",
    }),
  );
  sockets[0].message({
    type: "command_ack",
    command_id: "reply-1",
    command_type: "submit_user_reply",
    accepted: false,
    turn_id: "turn-1",
    error_code: "turn_not_waiting_input",
    message: "not awaiting",
    protocol_version: "2.0",
  });

  assert.equal(await verdict, false);
});

test("an accepted reply resolves true", async () => {
  const { client, sockets } = harness();
  client.connect();
  sockets[0].open();

  const verdict = client.sendAwaitingAck(
    buildSubmitUserReply({
      turnId: "turn-1",
      text: "B",
      commandId: "reply-2",
    }),
  );
  sockets[0].message({
    type: "command_ack",
    command_id: "reply-2",
    command_type: "submit_user_reply",
    accepted: true,
    turn_id: "turn-1",
    error_code: "",
    message: "",
    protocol_version: "2.0",
  });

  assert.equal(await verdict, true);
});

test("stopping releases waiters that will never be acknowledged", async () => {
  const { client, sockets } = harness();
  client.connect();
  sockets[0].open();

  const verdict = client.sendAwaitingAck(
    buildSubmitUserReply({
      turnId: "turn-1",
      text: "B",
      commandId: "reply-3",
    }),
  );
  client.stop();

  assert.equal(await verdict, false);
});
