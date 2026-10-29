import { test } from "node:test";
import assert from "node:assert/strict";
import { runLoop } from "../src/core/run-loop.js";
import { HostFailure } from "../src/core/contracts.js";
import type { LoopConfig, LoopHost, LoopState, Operation, Operations, RoundFacts } from "../src/core/contracts.js";

const answer: RoundFacts = { hasTools: false, hasText: true, truncated: false, reasoningBudgetExhausted: false };
const tools: RoundFacts = { ...answer, hasTools: true };
const empty: RoundFacts = { ...answer, hasText: false };
const config: LoopConfig = { explorationBudget: 2, settlementBudget: 3, emptyRecoveryBudget: 2 };

class Script implements LoopHost {
  calls: Array<{ operation: Operation; input: unknown; state: Readonly<LoopState> }> = [];
  recovery = false;
  redirect = false;
  override = false;
  pause = false;
  resumed = true;
  terminate = false;
  controller = new AbortController();
  cancelAt: Operation | undefined;
  constructor(readonly rounds: Array<RoundFacts | Error>) {}
  async invoke<K extends Operation>(operation: K, input: Operations[K]["input"], state: Readonly<LoopState>): Promise<Operations[K]["output"]> {
    this.calls.push({ operation, input, state });
    if (operation === this.cancelAt) this.controller.abort();
    let result: unknown = null;
    switch (operation) {
      case "call_round": {
        const round = this.rounds.shift();
        if (round instanceof Error) throw round;
        if (!round) throw new Error("Unexpected model call");
        result = round;
        break;
      }
      case "prepare_recovery": result = { available: this.recovery, rejected: false }; break;
      case "check_finish": result = { redirect: this.redirect, override: this.override }; break;
      case "dispatch_tools": result = { pause: this.pause }; break;
      case "resolve_pause": result = this.resumed; break;
      case "after_tools": result = { override: this.override, terminate: this.terminate }; break;
      case "forced_finish": result = { extraRounds: 1 }; break;
      case "raise_reasoning_budget": throw new HostFailure("reasoning budget", "budget", false);
    }
    return result as Operations[K]["output"];
  }
  run(override: Partial<LoopConfig> = {}) { return runLoop(this, { ...config, ...override }, this.controller.signal); }
  operations() { return this.calls.map(c => c.operation); }
}

test("plain answer takes one round and does not invoke tools", async () => {
  const host = new Script([answer]);
  assert.equal((await host.run()).rounds, 1);
  assert.deepEqual(host.operations(), ["call_round", "check_finish", "finish"]);
});

test("tools finish before the next model call and own an independent step counter", async () => {
  const host = new Script([tools, answer]);
  const state = await host.run();
  assert.equal(state.tool_steps, 1);
  assert.equal(state.rounds, 2);
  assert.deepEqual(host.operations(), ["call_round", "dispatch_tools", "after_tools", "call_round", "check_finish", "finish"]);
});

test("budget allows bounded settlement then exactly one tool-less hard finish", async () => {
  const host = new Script(Array.from({ length: 5 }, () => tools));
  assert.deepEqual(await host.run(), { rounds: 6, exploration_rounds: 2, settlement_rounds: 3, tool_steps: 5, reasoning_budget_recoveries: 0 });
  assert.equal(host.operations().filter(x => x === "begin_settlement").length, 1);
  assert.equal(host.operations().at(-1), "forced_finish");
});

test("zero settlement budget immediately hard-finishes after exploration", async () => {
  const host = new Script([tools]);
  assert.equal((await host.run({ explorationBudget: 1, settlementBudget: 0 })).rounds, 2);
  assert.ok(!host.operations().includes("begin_settlement"));
});

test("pause resumes in protocol without folding a checkpoint early", async () => {
  const host = new Script([tools, answer]); host.pause = true;
  await host.run();
  assert.deepEqual(host.operations(), ["call_round", "dispatch_tools", "resolve_pause", "call_round", "check_finish", "finish"]);
});

test("unresolved pause returns without finalizing or spending another round", async () => {
  const host = new Script([tools]); host.pause = true; host.resumed = false;
  assert.equal((await host.run()).rounds, 1);
  assert.equal(host.operations().at(-1), "resolve_pause");
});

test("truncated answer continues under the same total round budget", async () => {
  const host = new Script([{ ...answer, truncated: true }, answer]);
  assert.equal((await host.run()).rounds, 2);
  assert.equal(host.operations()[1], "continue_truncated");
});

test("repeated reasoning budget exhaustion raises instead of empty success", async () => {
  const exhausted = { ...empty, reasoningBudgetExhausted: true };
  const host = new Script([exhausted, exhausted]);
  await assert.rejects(host.run(), /reasoning budget/);
  assert.ok(!host.operations().includes("finish"));
  assert.ok(!host.operations().includes("forced_finish"));
});

test("two empty rounds force a final response", async () => {
  const host = new Script([empty, empty]);
  assert.equal((await host.run()).rounds, 3);
  assert.equal(host.operations().at(-1), "forced_finish");
});

test("capability guard redirects once then rejects", async () => {
  const host = new Script([answer, answer]); host.redirect = true;
  await host.run();
  assert.equal(host.operations().filter(x => x === "redirect_finish").length, 1);
  assert.equal(host.operations().at(-1), "reject_finish");
});

test("capability override precedes a terminator after tools", async () => {
  const host = new Script([tools]); host.override = true; host.terminate = true;
  await host.run();
  assert.equal(host.operations().at(-1), "finish");
  assert.deepEqual(host.calls.at(-1)?.input, { override: true });
});

test("terminator does not ask the model for another response", async () => {
  const host = new Script([tools]); host.terminate = true;
  await host.run();
  assert.equal(host.operations().at(-1), "terminate");
});

test("first-round provider errors preserve failure", async () => {
  const error = new HostFailure("provider unavailable", "1", false);
  const host = new Script([error]);
  await assert.rejects(host.run(), e => e === error);
  assert.deepEqual(host.operations(), ["call_round"]);
});

test("later error can salvage completed work", async () => {
  const host = new Script([tools, new HostFailure("provider unavailable", "2", false)]);
  assert.equal((await host.run()).rounds, 2);
  assert.deepEqual(host.calls.at(-1)?.input, { reason: "error", error: "provider unavailable" });
});

test("partial visible output never triggers an implicit retry", async () => {
  const error = new HostFailure("partial", "2", true);
  const host = new Script([tools, error]);
  await assert.rejects(host.run(), e => e === error);
  assert.ok(!host.operations().includes("forced_finish"));
});

for (const operation of ["call_round", "dispatch_tools", "resolve_pause"] as const) {
  test(`cancellation during ${operation} never starts another effect`, async () => {
    const host = new Script([tools, answer]); host.pause = true; host.cancelAt = operation;
    await assert.rejects(host.run(), { name: "AbortError" });
    assert.equal(host.operations().at(-1), operation);
  });
}

test("invalid budgets are rejected before invoking any effect", async () => {
  for (const explorationBudget of [0, -1, Infinity, NaN, 1.5, 100_001]) {
    const host = new Script([answer]);
    await assert.rejects(host.run({ explorationBudget }), /Invalid loop budget/);
    assert.deepEqual(host.calls, []);
  }
});


test("source recovery gets one restricted delivery round within the hard budget", async () => {
  const host = new Script([tools, tools, answer]);
  host.recovery = true;
  assert.equal((await host.run({ explorationBudget: 1, settlementBudget: 1 })).rounds, 3);
  assert.equal(host.operations().at(-1), "finish");
  assert.ok(!host.operations().includes("forced_finish"));
});

test("recovery cannot reopen exploration or dispatch a rejected tool batch", async () => {
  for (const rejected of [false, true]) {
    const host = new Script([tools, tools, { ...tools, recoveryRejected: rejected }]);
    host.recovery = true;
    const state = await host.run({ explorationBudget: 1, settlementBudget: 1 });
    assert.equal(state.rounds, 3);
    assert.equal(state.tool_steps, rejected ? 2 : 3);
    assert.equal(host.operations().at(-1), "reject_finish");
    assert.ok(!host.operations().includes("forced_finish"));
  }
});

test("failed capability prerequisites propagate without a salvage call", async () => {
  const host = new Script([tools, new HostFailure("source unavailable", "prerequisite", false, true)]);
  await assert.rejects(host.run(), /source unavailable/);
  assert.ok(!host.operations().includes("forced_finish"));
});
