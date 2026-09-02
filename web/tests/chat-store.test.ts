import assert from "node:assert/strict";
import test from "node:test";

import type { ChatMessage, ChatSession } from "../features/chat/model/types";
import { createChatStore } from "../features/chat/store/createChatStore";
import { MAX_CACHED_CHAT_SESSIONS } from "../features/chat/store/reducer";

const user = (id: number): ChatMessage => ({
  id,
  role: "user",
  content: "question",
  parentMessageId: null,
});
const assistant = (id: number, content = ""): ChatMessage => ({
  id,
  role: "assistant",
  content,
  parentMessageId: id - 1,
  events: [],
});

test("chat reducer handles optimistic streaming, replay dedupe, and terminal truth", () => {
  const store = createChatStore();
  store.dispatch({ type: "ensure_session", key: "draft" });
  store.dispatch({
    type: "add_optimistic_turn",
    key: "draft",
    user: user(-2),
    assistant: assistant(-1),
  });
  const event = {
    type: "content" as const,
    turn_id: "turn-1",
    seq: 1,
    timestamp: 1,
    content: "answer",
    metadata: {},
  };
  store.dispatch({ type: "stream_event", key: "draft", event });
  store.dispatch({ type: "stream_event", key: "draft", event });
  store.dispatch({
    type: "turn_status",
    key: "draft",
    status: "waiting_input",
    turnId: "turn-1",
  });

  const session = store.getState().sessions.draft;
  assert.equal(session.messages.at(-1)?.content, "answer");
  assert.equal(session.messages.at(-1)?.events?.length, 1);
  assert.equal(session.queryState, "waiting_input");
});

test("branching, delete, regenerate rollback, and metadata remain session scoped", () => {
  const store = createChatStore();
  store.dispatch({ type: "ensure_session", key: "one" });
  store.dispatch({
    type: "add_optimistic_turn",
    key: "one",
    user: user(1),
    assistant: assistant(2, "old"),
  });
  store.dispatch({
    type: "set_branch",
    key: "one",
    parentKey: "null",
    childId: 1,
  });
  store.dispatch({ type: "delete_messages", key: "one", ids: [1, 2] });
  store.dispatch({
    type: "regenerate_rollback",
    key: "one",
    assistant: assistant(2, "old"),
  });
  store.dispatch({ type: "session_meta", key: "one", title: "Stable title" });
  assert.equal(store.getState().sessions.one.title, "Stable title");
  assert.equal(store.getState().sessions.one.messages.at(-1)?.content, "old");
  assert.equal(store.getState().sessions.one.selectedBranches.null, 1);
});

test("cache bounds evict old idle sessions and retain live work", () => {
  const store = createChatStore();
  for (let index = 0; index < MAX_CACHED_CHAT_SESSIONS + 3; index += 1) {
    const session: ChatSession = {
      key: `s${index}`,
      id: `s${index}`,
      title: `Session ${index}`,
      messages: [],
      status: index === 0 ? "running" : "idle",
      queryState: index === 0 ? "running" : "idle",
      activeTurnId: index === 0 ? "turn-live" : null,
      lastSeq: 0,
      cancellationRequested: false,
      selectedBranches: {},
      updatedAt: index,
    };
    store.dispatch({ type: "load_session", session });
  }
  assert.ok(
    Object.keys(store.getState().sessions).length <=
      MAX_CACHED_CHAT_SESSIONS + 1,
  );
  assert.ok(store.getState().sessions.s0);
});
