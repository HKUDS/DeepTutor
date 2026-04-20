import test from "node:test";
import assert from "node:assert/strict";

import { firstParam } from "../lib/route-params.ts";

test("firstParam returns undefined for missing param", () => {
  assert.equal(firstParam(undefined), undefined);
});

test("firstParam returns scalar param unchanged", () => {
  assert.equal(firstParam("ielts-tutor"), "ielts-tutor");
});

test("firstParam returns first element for catch-all array", () => {
  assert.equal(firstParam(["ielts-tutor", "extra"]), "ielts-tutor");
});
