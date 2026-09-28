import test from "node:test";
import assert from "node:assert/strict";
import {
  extractAskUserPayload,
  extractMessageSegments,
  leadingTraceEvents,
} from "../components/chat/home/AskUserOptions";
import type { StreamEvent } from "../features/chat/model/protocol";
import { decodeEscapedUnicodeForDisplay } from "../lib/markdown-display";

function event(
  type: StreamEvent["type"],
  metadata: Record<string, unknown> = {},
  content = "",
): StreamEvent {
  return {
    type,
    source: "chat",
    stage: "responding",
    content,
    metadata,
    session_id: "session-1",
    turn_id: "turn-1",
    seq: 1,
    timestamp: 0,
  };
}

const askUserCard = (toolCallId: string) =>
  event("tool_result", {
    tool_call_id: toolCallId,
    tool_metadata: {
      ask_user: {
        questions: [
          {
            id: "q1",
            prompt: "Which is the general form?",
            options: [{ label: "A" }, { label: "B" }],
          },
        ],
      },
    },
  });

const resolved = (toolCallId: string) =>
  event("progress", {
    ask_user_resolved: true,
    ask_user_tool_call_id: toolCallId,
    answers: [{ questionId: "q1", text: "B" }],
  });

test("work is laid out between the text that introduced it and what followed", () => {
  // The shape the whole change exists for: say what you are about to do, do
  // it, say what came of it — in that order, in one bubble.
  const segments = extractMessageSegments([
    event(
      "content",
      { call_id: "round-1", call_kind: "agent_loop_round" },
      "Let me look that up.",
    ),
    event("tool_call", { call_id: "tool-1" }, "web_search"),
    event("tool_result", { call_id: "tool-1" }, "three results"),
    event(
      "content",
      { call_id: "round-2", call_kind: "agent_loop_round" },
      "It is 1957.",
    ),
  ]);

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["text", "trace", "text"],
  );
  assert.equal(
    segments[0].kind === "text" && segments[0].text,
    "Let me look that up.",
  );
  assert.equal(segments[2].kind === "text" && segments[2].text, "It is 1957.");
});

test("a fresh run of work opens below the text that follows the previous one", () => {
  const segments = extractMessageSegments([
    event(
      "content",
      { call_id: "r1", call_kind: "agent_loop_round" },
      "First,",
    ),
    event("tool_call", { call_id: "t1" }, "read_source"),
    event("content", { call_id: "r2", call_kind: "agent_loop_round" }, "Now,"),
    event("tool_call", { call_id: "t2" }, "web_search"),
    event("content", { call_id: "r3", call_kind: "agent_loop_round" }, "Done."),
  ]);

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["text", "trace", "text", "trace", "text"],
  );
  // Each region holds only its own call, not everything that came before.
  const first = segments[1];
  const second = segments[3];
  assert.equal(first.kind === "trace" && first.events.length, 1);
  assert.equal(second.kind === "trace" && second.events.length, 1);
});

test("a reloaded turn keeps each run of work under its own paragraph", () => {
  // The event preview a settled turn is restored from carries no `content`,
  // so the two calls arrive back to back with nothing between them. Only the
  // boundary each recorded still says which paragraph it belonged under —
  // without it both rows collapsed into one block and the reload no longer
  // resembled the turn the reader had watched.
  const first = "Let me look that up.\n\n";
  const second = "That confirms it. Checking one more thing.\n\n";
  const closing = "So the answer is 1957.";
  const segments = extractMessageSegments(
    [
      event("tool_call", {
        call_id: "t1",
        assistant_content_offset: first.length,
      }),
      event("tool_result", { call_id: "t1" }, "a source"),
      event("tool_call", {
        call_id: "t2",
        assistant_content_offset: (first + second).length,
      }),
      event("tool_result", { call_id: "t2" }, "three results"),
      event("done", { status: "completed" }),
    ],
    first + second + closing,
  );

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["text", "trace", "text", "trace", "text"],
  );
  assert.equal(segments[0].kind === "text" && segments[0].text, first);
  assert.equal(segments[2].kind === "text" && segments[2].text, second);
  assert.equal(segments[4].kind === "text" && segments[4].text, closing);
});

test("reasoning produced after a card becomes its own segment below it", () => {
  const before = event(
    "thinking",
    { call_id: "round-1" },
    "planning a question",
  );
  const after = event(
    "thinking",
    { call_id: "round-2" },
    "grading their answer",
  );

  const segments = extractMessageSegments([
    before,
    askUserCard("call-1"),
    resolved("call-1"),
    after,
    event(
      "content",
      { call_id: "round-2", call_kind: "agent_loop_round" },
      "Correct!",
    ),
  ]);

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["trace", "ask_user", "trace", "text"],
  );
  const beforeCard = segments[0];
  assert.equal(
    beforeCard.kind === "trace" && beforeCard.events[0].content,
    "planning a question",
  );
  const afterCard = segments[2];
  // The first answer delta closes the preceding thinking disclosure.
  assert.equal(afterCard.kind === "trace" && afterCard.events.length, 2);
  assert.equal(afterCard.kind === "trace" && afterCard.events[1].content, "Correct!");
  assert.equal(
    afterCard.kind === "trace" && afterCard.events[0].content,
    "grading their answer",
  );
});

test("every round is claimed inline, leaving the header block nothing to show", () => {
  // Trace rows render where the work happened. Anything still handed to the
  // pinned activity block would be the same step shown a second time.
  const before = event("thinking", { call_id: "round-1" }, "planning");
  const after = event("thinking", { call_id: "round-2" }, "grading");
  const events = [before, askUserCard("call-1"), resolved("call-1"), after];

  const leading = leadingTraceEvents(events, extractMessageSegments(events));

  // Nothing at all: the reasoning is claimed by its inline region, and the
  // card's own events render as the card rather than as a bare tool row.
  assert.deepEqual(leading, []);
});

test("a turn with no tool work is a single run of prose", () => {
  const events = [
    event("thinking", { call_id: "round-1" }, "thinking"),
    event(
      "content",
      { call_id: "round-1", call_kind: "agent_loop_round" },
      "answer",
    ),
  ];
  const segments = extractMessageSegments(events);

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["trace", "text"],
  );
  // The inline trace also claims the first answer delta as its closing marker.
  assert.deepEqual(leadingTraceEvents(events, segments), []);
});

test("each card gets the rounds that followed it", () => {
  const segments = extractMessageSegments([
    askUserCard("call-1"),
    resolved("call-1"),
    event("thinking", { call_id: "round-2" }, "first follow-up"),
    askUserCard("call-2"),
    resolved("call-2"),
    event("thinking", { call_id: "round-3" }, "second follow-up"),
  ]);

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["ask_user", "trace", "ask_user", "trace"],
  );
});

test("ask_user card prompts decode dense non-ASCII unicode escapes (#973)", () => {
  const escaped =
    "\\u300c\\u6570\\u5236\\u8f6c\\u6362\\u300d\\u8fd8\\u6ca1\\u8fc7\\u5173";
  assert.equal(decodeEscapedUnicodeForDisplay(escaped), "「数制转换」还没过关");

  const card = extractAskUserPayload([
    event("tool_result", {
      tool_call_id: "call-1",
      tool_metadata: {
        ask_user: {
          intro: escaped,
          questions: [
            {
              id: "q1",
              prompt: escaped,
              header: "\\u6570\\u5236\\u8f6c\\u6362",
              options: [
                {
                  label: "A",
                  description: "\\u7ee7\\u7eed\\u7b54\\u9898",
                },
              ],
            },
          ],
        },
      },
    }),
  ]);

  assert.ok(card);
  assert.equal(card.payload.intro, "「数制转换」还没过关");
  assert.equal(card.payload.questions[0].prompt, "「数制转换」还没过关");
  assert.equal(card.payload.questions[0].header, "数制转换");
  assert.equal(card.payload.questions[0].options[0].description, "继续答题");
});

// A settled message keeps only a semantic preview of its trace (and the
// session endpoint serves the same preview on reload): no content events.
const previewCard = (toolCallId: string) =>
  event("tool_result", {
    tool_call_id: toolCallId,
    tool_metadata: {
      ask_user: {
        questions: [
          {
            id: "q1",
            prompt: "Which reducer keeps history?",
            options: [{ label: "A" }, { label: "B" }],
          },
        ],
      },
    },
  });

const masteryCard = (toolCallId: string) =>
  event("tool_result", {
    tool_call_id: toolCallId,
    tool_metadata: {
      mastery_question: {
        question_id: "q1",
        prompt: "Which reducer keeps history?",
        question_type: "choice",
        objective: { id: "kp1", name: "Reducers" },
        difficulty: "medium",
        attempt: 1,
        options: [
          { label: "A", body: "overwrite" },
          { label: "B", body: "accumulate" },
        ],
        allow_free_text: true,
      },
    },
  });

test("a posed mastery question is its own segment, not an ask_user card", () => {
  const answer = "Plain fields overwrite; reducers accumulate.\n\nLet's check:";
  const segments = extractMessageSegments(
    [
      event("tool_call", { tool_name: "mastery_quiz" }),
      masteryCard("call-1"),
      event("done", { status: "completed" }),
    ],
    answer,
  );

  // The `mastery_quiz` call carries no call_id of its own, so there is no row
  // to draw for it and the region it opened is dropped rather than left as an
  // empty gap.
  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["text", "mastery_question"],
  );
  // The whole settled answer lays out above the card that ended the turn.
  assert.equal(segments[0].kind === "text" && segments[0].text, answer);
  const card = segments[1];
  assert.equal(
    card.kind === "mastery_question" && card.question.objectiveName,
    "Reducers",
  );
});

test("a card's call keeps its row, but nothing else of that call does", () => {
  // Stopping to ask is a step, and the trace is where steps are recorded: with
  // the row suppressed, an answered exchange read as though the answers had
  // arrived on their own. What the row must not do is restate the card, so the
  // call's *result* — the payload the card is built from — stays out.
  const call = event(
    "tool_call",
    { call_id: "call-1", tool_call_id: "call-1", tool_name: "ask_user" },
    "ask_user",
  );
  const segments = extractMessageSegments([
    event(
      "content",
      { call_id: "r1", call_kind: "agent_loop_round" },
      "First, a question.",
    ),
    call,
    askUserCard("call-1"),
  ]);

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["text", "trace", "ask_user"],
  );
  const trace = segments[1];
  assert.deepEqual(trace.kind === "trace" && trace.events, [call]);
});

test("a mastery card posed on the old ask_user channel still reads as one", () => {
  // History holds cards posed before mastery questions got their own key.
  const legacy = event("tool_result", {
    tool_call_id: "call-1",
    tool_metadata: {
      ask_user: {
        kind: "mastery_question",
        questions: [{ id: "q1", prompt: "Which reducer keeps history?" }],
        mastery_question: {
          question_id: "q1",
          prompt: "Which reducer keeps history?",
          question_type: "choice",
          objective: { id: "kp1", name: "Reducers" },
          attempt: 1,
          options: [{ label: "A", body: "overwrite" }],
        },
      },
    },
  });

  const segments = extractMessageSegments([legacy], "Check:");

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["text", "mastery_question"],
  );
});

test("a resolved card splits the settled answer at its stamped offset", () => {
  const intro = "Two ways to read this.\n\n";
  const reply = "Since you picked B, here is why it holds.";
  const segments = extractMessageSegments(
    [
      previewCard("call-1"),
      event("progress", {
        ask_user_resolved: true,
        ask_user_tool_call_id: "call-1",
        answers: [{ questionId: "q1", text: "B" }],
        assistant_content_offset: intro.length,
      }),
      event("done", { status: "completed" }),
    ],
    intro + reply,
  );

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["text", "ask_user", "text"],
  );
  assert.equal(segments[0].kind === "text" && segments[0].text, intro);
  assert.equal(
    segments[1].kind === "ask_user" && segments[1].data.resolved,
    true,
  );
  assert.equal(segments[2].kind === "text" && segments[2].text, reply);
});

test("an offset measured before the CJK repair still cuts at the paragraph", () => {
  // The stored text gained two spaces from the emphasis repair, so the
  // stamped offset now points two characters into the intro's last line.
  const intro = "这里有 **「两」** 种读法。\n\n";
  const reply = "你选了 B，原因如下。";
  const segments = extractMessageSegments(
    [
      previewCard("call-1"),
      event("progress", {
        ask_user_resolved: true,
        ask_user_tool_call_id: "call-1",
        assistant_content_offset: intro.length - 2,
      }),
    ],
    intro + reply,
  );

  assert.equal(segments[0].kind === "text" && segments[0].text, intro);
  assert.equal(segments[2].kind === "text" && segments[2].text, reply);
});

test("streamed content keeps precedence over the persisted answer", () => {
  const segments = extractMessageSegments(
    [
      event(
        "content",
        { call_id: "round-1", call_kind: "agent_loop_round" },
        "live text",
      ),
      askUserCard("call-1"),
    ],
    "persisted text",
  );

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["text", "ask_user"],
  );
  assert.equal(segments[0].kind === "text" && segments[0].text, "live text");
});

/* ---------------- streaming previews (``ask_user_draft``) ---------------- */

const draft = (
  callId: string | null,
  payload: Record<string, unknown>,
): StreamEvent =>
  event("progress", {
    trace_kind: "ask_user_draft",
    tool_name: "ask_user",
    ...(callId === null ? {} : { draft_call_id: callId }),
    ask_user_draft: payload,
  });

test("an intro-only draft already puts a read-only card in the thread", () => {
  const segments = extractMessageSegments(
    [draft("call-1", { intro: "Which path?", questions: [] })],
    "",
    { streaming: true },
  );

  assert.equal(segments.length, 1);
  assert.ok(segments[0].kind === "ask_user");
  if (segments[0].kind !== "ask_user") return;
  assert.equal(segments[0].data.streaming, true);
  assert.equal(segments[0].data.payload.intro, "Which path?");
  assert.deepEqual(segments[0].data.payload.questions, []);
});

test("successive drafts grow one card instead of stacking new ones", () => {
  const segments = extractMessageSegments(
    [
      draft("call-1", { intro: "Which path?", questions: [] }),
      draft("call-1", {
        intro: "Which path?",
        questions: [{ id: "q1", prompt: "Which one?", options: [] }],
      }),
      draft("call-1", {
        intro: "Which path?",
        questions: [
          { id: "q1", prompt: "Which one?", options: [{ label: "A" }] },
        ],
      }),
    ],
    "",
    { streaming: true },
  );

  assert.equal(segments.length, 1);
  if (segments[0].kind !== "ask_user") return assert.fail("expected a card");
  assert.equal(segments[0].data.payload.questions[0].options.length, 1);
});

test("the dispatched result promotes the preview in place, keeping its key", () => {
  const events = [
    draft("call-1", { intro: "Which path?", questions: [] }),
    // Responses-API calls are dispatched under "<call id>|<item id>".
    askUserCard("call-1|item-9"),
  ];
  const streamed = extractMessageSegments(events.slice(0, 1), "", {
    streaming: true,
  });
  const promoted = extractMessageSegments(events, "", { streaming: true });

  assert.equal(promoted.length, 1);
  if (promoted[0].kind !== "ask_user") return assert.fail("expected a card");
  assert.equal(promoted[0].data.streaming, undefined);
  assert.equal(promoted[0].toolCallId, "call-1|item-9");
  assert.equal(promoted[0].data.payload.questions.length, 1);
  // Same React key across the swap: the card must not remount and lose the
  // option the user may already have picked.
  assert.equal(promoted[0].key, streamed[0].key);
});

test("a promoted card still resolves from its answer event", () => {
  const segments = extractMessageSegments(
    [
      draft("call-1", { intro: "Which path?", questions: [] }),
      askUserCard("call-1|item-9"),
      resolved("call-1|item-9"),
    ],
    "",
    { streaming: true },
  );

  assert.equal(segments.length, 1);
  if (segments[0].kind !== "ask_user") return assert.fail("expected a card");
  assert.equal(segments[0].data.resolved, true);
  assert.deepEqual(segments[0].data.answers, [{ questionId: "q1", text: "B" }]);
});

test("a preview that never became a call is dropped once the turn settles", () => {
  const events = [
    event(
      "content",
      { call_id: "round-1", call_kind: "agent_loop_round" },
      "here is the question",
    ),
    draft("call-1", { intro: "Which path?", questions: [] }),
  ];

  assert.deepEqual(
    extractMessageSegments(events, "", { streaming: true }).map((s) => s.kind),
    ["text", "ask_user"],
  );
  assert.deepEqual(
    extractMessageSegments(events, "", { streaming: false }).map((s) => s.kind),
    ["text"],
  );
});

test("dropping a settled preview does not shift another card's text offset", () => {
  const intro = "First half.\n\n";
  const reply = "Second half.";
  const segments = extractMessageSegments(
    [
      draft("call-2", { intro: "never dispatched", questions: [] }),
      askUserCard("call-1"),
      event("progress", {
        ask_user_resolved: true,
        ask_user_tool_call_id: "call-1",
        assistant_content_offset: intro.length,
      }),
    ],
    intro + reply,
    { streaming: false },
  );

  assert.deepEqual(
    segments.map((segment) => segment.kind),
    ["text", "ask_user", "text"],
  );
  assert.equal(segments[0].kind === "text" && segments[0].text, intro);
  assert.equal(segments[2].kind === "text" && segments[2].text, reply);
});

test("a preview without a call id is still promoted by the result", () => {
  const segments = extractMessageSegments(
    [
      draft(null, { intro: "Which path?", questions: [] }),
      askUserCard("call-1"),
    ],
    "",
    { streaming: true },
  );

  assert.equal(segments.length, 1);
  if (segments[0].kind !== "ask_user") return assert.fail("expected a card");
  assert.equal(segments[0].data.streaming, undefined);
});

test("extractAskUserPayload reports a draft as streaming, then the real call", () => {
  const events = [draft("call-1", { intro: "Which path?", questions: [] })];
  const draftOnly = extractAskUserPayload(events, { streaming: true });
  assert.equal(draftOnly?.streaming, true);
  assert.equal(draftOnly?.resolved, false);

  // Once the turn has settled, a preview nobody can answer is not offered.
  assert.equal(extractAskUserPayload(events), null);

  const dispatched = extractAskUserPayload(
    [...events, askUserCard("call-1|item-9")],
    { streaming: true },
  );
  assert.equal(dispatched?.streaming, false);
  assert.equal(dispatched?.payload.questions.length, 1);
});
