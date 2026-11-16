import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

function source(file: string): string {
  return readFileSync(path.resolve(process.cwd(), file), "utf8");
}

/**
 * AssistantResponse is shared by every chat surface and reads both viewer
 * context even when a mastery turn has no reading attachment.
 * Missing the provider makes an existing assistant message throw during
 * render, before the bare `/sessions` route can initialise its new session.
 */
test("the mastery study route provides every shared chat viewer context", () => {
  const layout = source("app/(workspace)/layout.tsx");
  const sessionLayout = source("app/(workspace)/learning/mastery/[pathId]/sessions/layout.tsx");
  assert.doesNotMatch(sessionLayout, /ChatRuntimeProvider|ReadingProvider|WatchingProvider/);
  assert.match(sessionLayout, /<QuizFollowupProvider>/);
  assert.match(sessionLayout, /<GeogebraTabProvider>/);
  const response = source("components/common/AssistantResponse.tsx");

  assert.match(response, /useReading\(\)/);
  assert.match(layout, /import \{ ReadingProvider \}/);
  assert.match(layout, /<ReadingProvider>/);
  assert.match(layout, /<ChatRuntimeProvider>/);
});

test("mastery study exposes the shared transcript navigation and save actions", () => {
  const study = source("components/space/learning/MasteryStudy.tsx");

  assert.match(study, /<TurnNavigator/);
  assert.match(study, /data-chat-column="true"/);
  assert.match(study, /<SaveToNotebookModal/);
  assert.match(study, /aria-label=\{t\("Save to Notebook"\)\}/);
  assert.match(study, /source: "mastery_path"/);
});

test("a finished point offers the next one without jumping on its own", () => {
  // Confirming the lecture settles it and makes review available; it does not
  // navigate. The review tab is the learner's move, and the cue to start the
  // next section lives on the review page as a button. A self-healing roll
  // asks for a lecture if the runtime roll never landed.
  const study = source("components/space/learning/MasteryStudy.tsx");

  assert.match(study, /Next knowledge point/);
  assert.doesNotMatch(study, /openPlaced\("review", viewedPoint\.id\)/);
  assert.match(study, /rollPointLectureDraft/);
  assert.doesNotMatch(study, /navigateToPlaced\("study", nextPoint\.id\)/);
});

test("the mastery answer dock resets a re-posed question", () => {
  const study = source("components/space/learning/MasteryStudy.tsx");

  // Keyed by the question id so a question the tutor poses again gets a fresh
  // card instead of inheriting the previous submission's in-flight state, and
  // answering waits for the send so a card that could not be delivered reopens.
  assert.match(study, /key=\{openQuestion\.questionId\}/);
  assert.match(study, /answerMasteryQuestion = useCallback\(\s*async/);
});

test("the tutor's handoff never advances the path for the learner", () => {
  const study = source("components/space/learning/MasteryStudy.tsx");

  // A `study` handoff that opens a point other than this conversation's own is
  // the tutor moving the learner on; reaching the next point is the review
  // page's button, so the handoff is recorded and not followed. The prompt asks
  // the tutor not to do it; this is the part that makes it deterministic.
  assert.match(study, /found\.mode === "study"/);
  assert.match(study, /found\.knowledgePointId !== bound/);
});

test("the lecture card waits for the section to be mastered", () => {
  const study = source("components/space/learning/MasteryStudy.tsx");

  // The runtime rolls a draft as soon as the point is taught, so the card is
  // mounted for the whole study sitting and reads whatever draft exists. But it
  // must not be offered while the tutor is still asking questions: that reads
  // as "this section is finished" when it is not.
  assert.match(study, /viewedPointStatus === "mastered"/);
});
