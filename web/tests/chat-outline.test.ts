import test from "node:test";
import assert from "node:assert/strict";
import {
  buildChatOutline,
  plainTextPreview,
  turnAnchorKey,
} from "../lib/chat-outline";

type Msg = Parameters<typeof buildChatOutline>[0][number];

function conversation(): Msg[] {
  return [
    { id: 1, role: "user", content: "What is gradient descent?", parentMessageId: null },
    { id: 2, role: "assistant", content: "It **walks** downhill.", parentMessageId: 1 },
    { id: 3, role: "user", content: "And momentum?", parentMessageId: 2 },
    { id: 4, role: "assistant", content: "It smooths the path.", parentMessageId: 3 },
  ];
}

test("one entry per user turn, numbered and paired with its reply", () => {
  const outline = buildChatOutline(conversation(), {});
  assert.equal(outline.length, 2);
  assert.deepEqual(
    outline.map((e) => [e.ordinal, e.title, e.reply]),
    [
      [1, "What is gradient descent?", "It walks downhill."],
      [2, "And momentum?", "It smooths the path."],
    ],
  );
});

test("entry keys match the anchor the bubble renders", () => {
  const messages = conversation();
  const outline = buildChatOutline(messages, {});
  // The bubble receives its index within the visible path; the outline
  // must key off the same pair so the rail can find the DOM node.
  assert.equal(outline[0].key, turnAnchorKey(messages[0], 0));
  assert.equal(outline[1].key, turnAnchorKey(messages[2], 2));
});

test("id-less rows fall back to a positional key", () => {
  assert.equal(turnAnchorKey({ id: 7 }, 3), "m7");
  assert.equal(turnAnchorKey({ id: -1700000 }, 3), "m-1700000");
  assert.equal(turnAnchorKey({}, 3), "i3");
});

test("only the selected edit branch earns ticks", () => {
  const messages: Msg[] = [
    { id: 1, role: "user", content: "first draft", parentMessageId: null },
    { id: 2, role: "assistant", content: "draft reply", parentMessageId: 1 },
    { id: 3, role: "user", content: "edited draft", parentMessageId: null },
    { id: 4, role: "assistant", content: "edited reply", parentMessageId: 3 },
  ];
  // Default: latest sibling wins.
  assert.deepEqual(
    buildChatOutline(messages, {}).map((e) => e.title),
    ["edited draft"],
  );
  // Switching the branch reshapes the rail with the transcript.
  assert.deepEqual(
    buildChatOutline(messages, { null: 1 }).map((e) => e.title),
    ["first draft"],
  );
});

test("backend-synthesised user rows are not navigable", () => {
  const messages: Msg[] = [
    { id: 1, role: "user", content: "Quiz me", parentMessageId: null },
    { id: 2, role: "assistant", content: "Here you go.", parentMessageId: 1 },
    {
      id: 3,
      role: "user",
      content: "[Quiz Performance] 3/5 correct",
      parentMessageId: 2,
    },
    { id: 4, role: "assistant", content: "Review these.", parentMessageId: 3 },
  ];
  assert.deepEqual(
    buildChatOutline(messages, {}).map((e) => e.title),
    ["Quiz me"],
  );
});

test("system grounding rows never break the question/reply pairing", () => {
  const messages: Msg[] = [
    { id: 1, role: "user", content: "Explain entropy", parentMessageId: null },
    { id: 2, role: "system", content: "context blob", parentMessageId: 1 },
    { id: 3, role: "assistant", content: "Disorder, measured.", parentMessageId: 2 },
  ];
  const outline = buildChatOutline(messages, {});
  assert.equal(outline[0].reply, "Disorder, measured.");
});

test("a content-free planning turn does not hide the real answer", () => {
  const messages: Msg[] = [
    { id: 1, role: "user", content: "Research LLM routing", parentMessageId: null },
    { id: 2, role: "assistant", content: "", parentMessageId: 1 },
    { id: 3, role: "assistant", content: "Here is the report.", parentMessageId: 2 },
  ];
  assert.equal(buildChatOutline(messages, {})[0].reply, "Here is the report.");
});

test("weights are relative to the longest question in the session", () => {
  const messages: Msg[] = [
    { id: 1, role: "user", content: "hi", parentMessageId: null },
    { id: 2, role: "assistant", content: "hello", parentMessageId: 1 },
    { id: 3, role: "user", content: "x".repeat(120), parentMessageId: 2 },
  ];
  const [short, long] = buildChatOutline(messages, {});
  assert.equal(long.weight, 1);
  assert.ok(short.weight > 0 && short.weight < 0.3);
});

test("empty session yields no ticks", () => {
  assert.deepEqual(buildChatOutline([], {}), []);
});

test("preview flattens markdown to one readable line", () => {
  assert.equal(
    plainTextPreview("# Title\n\nSome **bold** and `code` text."),
    "Title Some bold and code text.",
  );
  assert.equal(
    plainTextPreview("See [the docs](https://example.com/a?b=c) for more."),
    "See the docs for more.",
  );
  assert.equal(plainTextPreview("![diagram](a.png)\n\nAfter."), "After.");
  assert.equal(
    plainTextPreview("Before\n```py\nprint('x')\n```\nAfter"),
    "Before After",
  );
  assert.equal(
    plainTextPreview("- one\n- two\n\n> quoted\n\n---\n\n1. three"),
    "one two quoted three",
  );
});

test("preview survives an unterminated code fence mid-stream", () => {
  assert.equal(plainTextPreview("Here:\n```py\nprint('x')"), "Here:");
});

test("preview truncates on a character budget with an ellipsis", () => {
  const long = plainTextPreview("word ".repeat(80), 40);
  assert.ok(long.length <= 41, long);
  assert.ok(long.endsWith("…"));
});
