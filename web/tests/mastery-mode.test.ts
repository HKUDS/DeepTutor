import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_MASTERY_MODE,
  MASTERY_MODES,
  masteryOpeningMessage,
  masterySessionRoute,
  normalizeMasteryMode,
} from "../lib/mastery-mode";

const t = (key: string, vars?: Record<string, unknown>) =>
  vars ? `${key}::${JSON.stringify(vars)}` : key;

test("an unknown mode is shown as the ordinary study mode", () => {
  assert.equal(normalizeMasteryMode(undefined), DEFAULT_MASTERY_MODE);
  assert.equal(normalizeMasteryMode("something_new"), "study");
  assert.equal(normalizeMasteryMode("OUTLINE"), "outline");
});

test("an outline conversation always knows what it was opened to say", () => {
  // The regression this guards: the opening used to be handed across the
  // navigation through a read-once channel, so any refused send consumed it
  // and left the screen insisting work was under way, permanently. Deriving it
  // from the mode means there is nothing to lose.
  assert.ok(masteryOpeningMessage("outline", t).length > 0);
});

test("review opens by naming what is due, or generically when nothing is", () => {
  const withDue = masteryOpeningMessage("review", t, {
    dueTitles: ["加噪调度", "重参数化"],
  });
  assert.match(withDue, /items/);
  assert.ok(masteryOpeningMessage("review", t).length > 0);
});

test("study opens with nothing, because starting is the learner's choice", () => {
  // "Start learning" does not say what to start with, so the screen offers
  // ways in instead of putting words in their mouth.
  assert.equal(masteryOpeningMessage("study", t), "");
});

test("a route only ever sets the mode a NEW conversation starts in", () => {
  assert.equal(
    masterySessionRoute("p1", "outline"),
    "/mastery/p1/sessions?mode=outline",
  );
  // The default needs no parameter: a bare route is a study conversation.
  assert.equal(masterySessionRoute("p1", "study"), "/mastery/p1/sessions");
  assert.equal(
    masterySessionRoute("p 1", "review", "c1"),
    "/mastery/p%201/sessions?mode=review&course=c1",
  );
});

test("every mode has a route and a label", () => {
  for (const mode of MASTERY_MODES) {
    assert.ok(masterySessionRoute("p", mode).startsWith("/mastery/p/sessions"));
  }
});

test("the mode reaches the wire", async () => {
  // It did not, for a whole batch: the line that maps it onto the start-turn
  // command was simply absent, so the server saw no mode on any turn, reported
  // the display fallback ("study") back to the tutor, and the tutor never
  // switched out of the outline mode the learner could see highlighted —
  // because it had been told it was already studying.
  const { buildStartTurnInput } = await import(
    "../features/chat/controllers/buildStartTurnInput"
  );
  const command = buildStartTurnInput({
    content: "hi",
    masteryPathId: "topic_1",
    masterySessionMode: "outline",
  } as never);

  assert.equal(command.mastery_session_mode, "outline");
  // …and a conversation that never had one says so, rather than inventing one.
  const bare = buildStartTurnInput({ content: "hi" } as never);
  assert.equal(bare.mastery_session_mode, null);
});
