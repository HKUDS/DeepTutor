import test from "node:test";
import assert from "node:assert/strict";

import { createSingleFlight } from "../lib/single-flight";

test("single-flight coalesces concurrent calls", async () => {
  let resolveLoader!: (value: string) => void;
  const calls: string[] = [];
  const load = createSingleFlight((argument: string) => {
    calls.push(argument);
    return new Promise<string>((resolve) => {
      resolveLoader = resolve;
    });
  });

  const first = load("focus");
  const second = load("pageshow");

  assert.strictEqual(second, first);
  assert.deepEqual(calls, ["focus"]);
  resolveLoader("models");
  assert.deepEqual(await Promise.all([first, second]), ["models", "models"]);
});

test("single-flight starts a fresh call after success or failure", async () => {
  let calls = 0;
  const load = createSingleFlight(async () => {
    calls += 1;
    if (calls === 1) throw new Error("temporary failure");
    return calls;
  });

  await assert.rejects(load(), /temporary failure/);
  assert.equal(await load(), 2);
});
