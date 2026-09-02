import test from "node:test";
import assert from "node:assert/strict";
import { extractMathAnimatorResult } from "../lib/math-animator-types";

test("extractMathAnimatorResult ignores generic response-only payloads", () => {
  assert.equal(
    extractMathAnimatorResult({
      response: "Hello! I'm DeepTutor.",
      metadata: {
        cost_summary: {
          total_cost_usd: 0,
          total_tokens: 1043,
          total_calls: 3,
        },
      },
    }),
    null,
  );
});

test("extractMathAnimatorResult keeps actual math animator payloads", () => {
  const result = extractMathAnimatorResult({
    response: "Storyboard generated.",
    output_mode: "image",
    artifacts: [
      {
        type: "image",
        url: "/api/files/frame-1.png",
        filename: "frame-1.png",
      },
    ],
  });

  assert.ok(result);
  assert.equal(result.output_mode, "image");
  assert.equal(result.artifacts.length, 1);
});
