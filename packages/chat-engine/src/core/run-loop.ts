import { HostFailure, validateConfig, validateOutput } from "./contracts.js";
import type { LoopConfig, LoopHost, LoopState, Operation, Operations } from "./contracts.js";

/** One scheduler for chat and partner turns, independent of HTTP, storage and providers. */
export async function runLoop(host: LoopHost, input: LoopConfig, signal: AbortSignal): Promise<LoopState> {
  const config = validateConfig(input);
  const state: LoopState = { rounds: 0, exploration_rounds: 0, settlement_rounds: 0, tool_steps: 0, reasoning_budget_recoveries: 0 };
  let settlementStarted = false;
  let emptyRecoveries = 0;
  let finishRedirectUsed = false;
  let recoveryUsed = false;

  const invoke = async <K extends Operation>(operation: K, args: Operations[K]["input"]): Promise<Operations[K]["output"]> => {
    signal.throwIfAborted();
    const result = await host.invoke(operation, args, { ...state });
    signal.throwIfAborted();
    return validateOutput(operation, result);
  };
  const forceFinish = async (reason: "budget" | "error" = "budget", error = "") => {
    const result = await invoke("forced_finish", { reason, error });
    state.rounds += result.extraRounds;
    return state;
  };

  while (true) {
    signal.throwIfAborted();
    const settling = state.exploration_rounds >= config.explorationBudget;
    if (settling) {
      if (state.settlement_rounds >= config.settlementBudget) {
        if (recoveryUsed) {
          await invoke("reject_finish", {});
          return state;
        }
        const recovery = await invoke("prepare_recovery", {});
        if (recovery.rejected) {
          await invoke("reject_finish", {});
          return state;
        }
        if (!recovery.available) return forceFinish();
        recoveryUsed = true;
      }
      if (!settlementStarted) {
        await invoke("begin_settlement", {});
        settlementStarted = true;
      }
    }
    let round;
    try {
      round = await invoke("call_round", { settling, first: state.rounds === 0 });
    } catch (error) {
      // A visible partial response must never be replayed, nor may cancellation
      // be converted into a successful salvage answer.
      signal.throwIfAborted();
      if (!(error instanceof HostFailure) || state.rounds === 0 || error.partialResponse || error.fatal) throw error;
      return forceFinish("error", error.message);
    }
    state.rounds++;
    if (settling) state.settlement_rounds++;
    else state.exploration_rounds++;

    if (round.recoveryRejected) {
      await invoke("reject_finish", {});
      return state;
    }
    if (!round.hasTools) {
      if (round.truncated || round.reasoningBudgetExhausted) {
        if (round.reasoningBudgetExhausted) {
          if (state.reasoning_budget_recoveries >= 1) await invoke("raise_reasoning_budget", {});
          state.reasoning_budget_recoveries++;
        }
        await invoke("continue_truncated", {});
        continue;
      }
      if (!round.hasText) {
        emptyRecoveries++;
        const force = emptyRecoveries >= config.emptyRecoveryBudget;
        await invoke("recover_empty", { force });
        if (force) return forceFinish();
        continue;
      }
      const decision = await invoke("check_finish", {});
      if (decision.redirect) {
        if (finishRedirectUsed) {
          await invoke("reject_finish", {});
          return state;
        }
        finishRedirectUsed = true;
        await invoke("redirect_finish", {});
        continue;
      }
      await invoke("finish", { override: decision.override });
      return state;
    }

    const dispatch = await invoke("dispatch_tools", {});
    state.tool_steps++;
    if (dispatch.pause) {
      if (await invoke("resolve_pause", {})) continue;
      return state;
    }
    const decision = await invoke("after_tools", {});
    if (decision.override) {
      await invoke("finish", { override: true });
      return state;
    }
    if (decision.terminate) {
      await invoke("terminate", {});
      return state;
    }
  }
}
