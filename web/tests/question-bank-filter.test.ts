import assert from "node:assert/strict";
import test from "node:test";

import { buildQuestionBankFilter } from "@/components/space/question-bank/useQuestionBank";

test("the unresolved view combines wrong answers with review state", () => {
  const filter = buildQuestionBankFilter(
    { kind: "unresolved" },
    { source: "mastery_path", materialId: "path-1", scoreTrend: "declined" },
    "equation",
    "oldest",
  );

  assert.deepEqual(filter, {
    category_id: undefined,
    uncategorized: undefined,
    bookmarked: undefined,
    is_correct: false,
    source: "mastery_path",
    material_id: "path-1",
    resolved: false,
    score_trend: "declined",
    search: "equation",
    sort: "oldest",
    limit: 60,
    course_id: undefined,
  });
});

test("review filters preserve the current course scope", () => {
  const filter = buildQuestionBankFilter(
    { kind: "all" },
    { source: "book", materialId: "book-1", scoreTrend: "" },
    "",
    "recent",
    "course-1",
  );

  assert.equal(filter.source, "book");
  assert.equal(filter.material_id, "book-1");
  assert.equal(filter.course_id, "course-1");
});
