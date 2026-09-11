import test from "node:test";
import assert from "node:assert/strict";

import {
  courseHandoffFrom,
  courseHandoffHref,
  extractCourseHandoffs,
  stripLeakedHandoffJson,
  targetAcceptsPrompt,
} from "../lib/course-handoff";
import { courseSessionConfiguration } from "../lib/course-session-scope";

function toolResult(handoff: Record<string, unknown>, nested = true) {
  const payload = { course_handoff: handoff };
  return {
    type: "tool_result",
    metadata: nested ? { tool_metadata: payload } : payload,
  };
}

test("a hand-off is read from the dispatcher's nested tool_metadata", () => {
  // The dispatcher nests a tool's own metadata under `tool_metadata`. Reading
  // only the top level type-checks fine and silently finds nothing.
  const payload = courseHandoffFrom(
    toolResult({
      target: "immersive_reading",
      prompt: "Start at the paging chapter",
      reason: "You cited it but never read it",
      ref_id: "ws_1",
      label: "OS textbook",
      course_id: "course_os",
    }),
  );

  assert.deepEqual(payload, {
    target: "immersive_reading",
    prompt: "Start at the paging chapter",
    reason: "You cited it but never read it",
    ref_id: "ws_1",
    label: "OS textbook",
    course_id: "course_os",
  });
});

test("top-level metadata still works, for callers that emit events directly", () => {
  const payload = courseHandoffFrom(
    toolResult({ target: "question_bank", course_id: "c1" }, false),
  );
  assert.equal(payload?.target, "question_bank");
  assert.equal(payload?.prompt, "");
});

test("an unrecognised target is refused rather than routed", () => {
  // The target is resolved against a route table, so accepting a free-form
  // value would turn the card into an open redirect.
  for (const target of [
    "https://evil.example/steal",
    "/settings/providers",
    "",
    42,
    null,
  ]) {
    assert.equal(courseHandoffFrom(toolResult({ target })), null);
  }
});

test("events that are not tool results carry no hand-off", () => {
  assert.equal(courseHandoffFrom({ type: "text", metadata: {} }), null);
  assert.equal(courseHandoffFrom({ type: "tool_result" }), null);
  assert.equal(
    courseHandoffFrom({ type: "tool_result", metadata: { other: 1 } }),
    null,
  );
});

test("two suggestions survive, a repeated one collapses", () => {
  const events = [
    toolResult({ target: "immersive_reading", ref_id: "ws_1" }),
    toolResult({ target: "mastery_path", ref_id: "p_1" }),
    toolResult({ target: "immersive_reading", ref_id: "ws_1" }),
  ] as unknown as Parameters<typeof extractCourseHandoffs>[0];

  const handoffs = extractCourseHandoffs(events);
  assert.equal(handoffs.length, 2);
  assert.deepEqual(
    handoffs.map((handoff) => handoff.target),
    ["immersive_reading", "mastery_path"],
  );
});

test("mastery hand-offs land on the study route, which has a composer", () => {
  // The path overview has no composer, so a prepared opening line sent there
  // would have nowhere to land.
  assert.equal(
    courseHandoffHref({
      target: "mastery_path",
      prompt: "",
      reason: "",
      ref_id: "path 1/a",
      label: "",
      course_id: "c1",
    }),
    "/mastery/path%201%2Fa/sessions?course=c1",
  );
});

test("specific reading hand-offs keep the course scope", () => {
  // Opening an existing workspace must not drop the learner back into an
  // unclassified conversation. The course id is already server-owned here.
  assert.equal(
    courseHandoffHref({
      target: "immersive_reading",
      prompt: "",
      reason: "",
      ref_id: "rw 1/a",
      label: "",
      course_id: "course os",
    }),
    "/reading/rw%201%2Fa?course=course%20os",
  );
});

test("study sessions carry the course scope", () => {
  const session = courseSessionConfiguration(
    { capability: "mastery_path", masteryPathId: "path_1" },
    " course_os ",
  );
  assert.deepEqual(session, {
    capability: "mastery_path",
    masteryPathId: "path_1",
    courseId: "course_os",
  });
});

test("a hand-off with no ref falls back to the surface's index, still scoped", () => {
  // The course has none of that kind yet, so the index is the honest
  // destination — but it must arrive carrying the course, or whatever the
  // learner builds there is stranded outside the course that sent them.
  const base = {
    prompt: "",
    reason: "",
    ref_id: "",
    label: "",
    course_id: "c1",
  };
  assert.equal(
    courseHandoffHref({ ...base, target: "immersive_reading" }),
    "/reading?course=c1",
  );
  assert.equal(
    courseHandoffHref({ ...base, target: "mastery_path" }),
    "/mastery?course=c1",
  );
});

test("global surfaces are handed the course so they can scope themselves", () => {
  const base = { prompt: "", reason: "", ref_id: "", label: "" };
  assert.equal(
    courseHandoffHref({
      ...base,
      target: "question_bank",
      course_id: "course a/b",
    }),
    "/space/questions?course=course%20a%2Fb",
  );
  assert.equal(
    courseHandoffHref({ ...base, target: "notebook", course_id: "c1" }),
    "/notebooks?course=c1",
  );
  assert.equal(
    courseHandoffHref({ ...base, target: "chat", course_id: "c1" }),
    "/chat?course=c1",
  );
});

test("only destinations with a composer are offered an opening line", () => {
  // Writing a prepared prompt for a list surface puts it in a slot nobody
  // reads — the card would promise an opening question that never arrives.
  assert.equal(targetAcceptsPrompt("chat", ""), true);
  assert.equal(targetAcceptsPrompt("mastery_path", "path_1"), true);
  assert.equal(targetAcceptsPrompt("immersive_reading", "rw_1"), true);
  assert.equal(targetAcceptsPrompt("question_bank", "q"), false);
  assert.equal(targetAcceptsPrompt("notebook", "n"), false);
});

test("a composer that only exists per-resource is not offered one without a ref", () => {
  // Without a ref these route to an index, which has nothing to type into and
  // never consumes the stored prompt. Offering one there does not merely fail
  // quietly: `setPendingPrompt` is scoped per destination and consumed on
  // arrival, so an opening line the learner declined would surface in whatever
  // path or workspace they opened next.
  assert.equal(targetAcceptsPrompt("mastery_path", ""), false);
  assert.equal(targetAcceptsPrompt("immersive_reading", "   "), false);
  // Chat's composer exists whether or not a resource is named.
  assert.equal(targetAcceptsPrompt("chat", ""), true);
});

test("a hand-off the model also printed as prose is not shown twice", () => {
  // Observed with gemini-3-flash-preview: the tool is called *and* its
  // arguments are written into the answer, so the card's contents appear above
  // it as raw JSON.
  const leaked = [
    "你目前正处于《操作系统》课程的起点。",
    "",
    '{ "target": "mastery_path", "reason": "这是大纲中的第一个单元。", "prompt": "请讲解操作系统的作用与目标。" }',
  ].join("\n");
  assert.equal(
    stripLeakedHandoffJson(leaked),
    "你目前正处于《操作系统》课程的起点。",
  );

  const fenced = [
    "Here is what to do next.",
    "",
    "```json",
    '{"target": "notebook", "reason": "collect these", "prompt": ""}',
    "```",
    "",
    "Take it when you are ready.",
  ].join("\n");
  assert.equal(
    stripLeakedHandoffJson(fenced),
    "Here is what to do next.\n\nTake it when you are ready.",
  );
});

test("stripping leaves JSON that is not a hand-off alone", () => {
  // A learner asking about a config file must get their answer back intact.
  const answer =
    'The shape is:\n\n```json\n{"target": "build/out", "reason": "why"}\n```\n\nUse it like that.';
  assert.equal(stripLeakedHandoffJson(answer), answer);

  // Right target, but missing the key `course_handoff` always requires.
  const partial = '{"target": "chat", "prompt": "hi"}';
  assert.equal(stripLeakedHandoffJson(partial), partial);

  const plain = "No JSON here at all.";
  assert.equal(stripLeakedHandoffJson(plain), plain);
});
