import test from "node:test";
import assert from "node:assert/strict";

import {
  isValidSkillName,
  SKILL_NAME_PATTERN,
  slugifySkillName,
} from "../lib/skill-slug";

test("slugifySkillName normalizes common free-text names", () => {
  assert.equal(
    slugifySkillName("Socratic Math Mentor"),
    "socratic-math-mentor",
  );
  assert.equal(slugifySkillName("My  Skill__v2"), "my-skill-v2");
  assert.equal(slugifySkillName("___Tutor!! 2026"), "tutor-2026");
});

test("slugifySkillName preserves valid hyphenated names", () => {
  assert.equal(slugifySkillName("proof-checker"), "proof-checker");
  assert.equal(slugifySkillName("math-v2"), "math-v2");
});

test("isValidSkillName mirrors backend skill name contract", () => {
  assert.equal(SKILL_NAME_PATTERN, "^[a-z0-9][a-z0-9-]{0,63}$");
  assert.equal(isValidSkillName("socratic-math-mentor"), true);
  assert.equal(isValidSkillName("a".repeat(64)), true);
  assert.equal(isValidSkillName(""), false);
  assert.equal(isValidSkillName("-teacher"), false);
  assert.equal(isValidSkillName("Teacher"), false);
  assert.equal(isValidSkillName("math_tutor"), false);
  assert.equal(isValidSkillName("a".repeat(65)), false);
});
