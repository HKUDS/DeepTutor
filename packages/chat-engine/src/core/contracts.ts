/** The scheduler owns counters and decisions; ports own effects and conversation data.
 * No provider credentials, prompts, messages or user identity cross the bridge.
 */
export interface LoopConfig {
  explorationBudget: number;
  settlementBudget: number;
  emptyRecoveryBudget: number;
}

export interface LoopState {
  rounds: number;
  exploration_rounds: number;
  settlement_rounds: number;
  tool_steps: number;
  reasoning_budget_recoveries: number;
}

export interface RoundFacts {
  recoveryRejected?: boolean;
  hasTools: boolean;
  hasText: boolean;
  truncated: boolean;
  reasoningBudgetExhausted: boolean;
}

export interface Operations {
  prepare_recovery: { input: Record<string, never>; output: { available: boolean; rejected: boolean } };
  begin_settlement: { input: Record<string, never>; output: null };
  call_round: { input: { settling: boolean; first: boolean }; output: RoundFacts };
  continue_truncated: { input: Record<string, never>; output: null };
  raise_reasoning_budget: { input: Record<string, never>; output: never };
  recover_empty: { input: { force: boolean }; output: null };
  check_finish: { input: Record<string, never>; output: { redirect: boolean; override: boolean } };
  redirect_finish: { input: Record<string, never>; output: null };
  reject_finish: { input: Record<string, never>; output: null };
  finish: { input: { override: boolean }; output: null };
  dispatch_tools: { input: Record<string, never>; output: { pause: boolean } };
  resolve_pause: { input: Record<string, never>; output: boolean };
  after_tools: { input: Record<string, never>; output: { override: boolean; terminate: boolean } };
  terminate: { input: Record<string, never>; output: null };
  forced_finish: { input: { reason: "budget" | "error"; error: string }; output: { extraRounds: number } };
}

export type Operation = keyof Operations;
export interface LoopHost {
  invoke<K extends Operation>(operation: K, input: Operations[K]["input"], state: Readonly<LoopState>): Promise<Operations[K]["output"]>;
}

export class HostFailure extends Error {
  constructor(message: string, readonly callId: string, readonly partialResponse: boolean, readonly fatal = false) {
    super(message);
    this.name = "HostFailure";
  }
}

export function validateConfig(value: unknown): LoopConfig {
  if (!value || typeof value !== "object") throw new Error("Missing loop config");
  const config = value as Record<string, unknown>;
  for (const key of ["explorationBudget", "settlementBudget", "emptyRecoveryBudget"] as const) {
    const n = config[key];
    if (typeof n !== "number" || !Number.isSafeInteger(n) || n < (key === "settlementBudget" ? 0 : 1) || n > 100_000) {
      throw new Error(`Invalid loop budget: ${key}`);
    }
  }
  return config as unknown as LoopConfig;
}

/** Runtime checks matter at the process boundary; TS types alone disappear. */
export function validateOutput<K extends Operation>(operation: K, value: unknown): Operations[K]["output"] {
  const record = value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
  let fields: string[] | undefined;
  switch (operation) {
    case "prepare_recovery": fields = ["available", "rejected"]; break;
    case "call_round": fields = ["hasTools", "hasText", "truncated", "reasoningBudgetExhausted"]; break;
    case "check_finish": fields = ["redirect", "override"]; break;
    case "dispatch_tools": fields = ["pause"]; break;
    case "after_tools": fields = ["override", "terminate"]; break;
    case "resolve_pause":
      if (typeof value !== "boolean") throw new Error("Invalid pause result");
      break;
    case "forced_finish":
      if (!record || (record.extraRounds !== 0 && record.extraRounds !== 1)) throw new Error("Invalid forced-finish accounting");
      break;
    case "raise_reasoning_budget": throw new Error("Budget exhaustion must terminate with an error");
    default:
      if (value !== null) throw new Error(`Unexpected result for ${operation}`);
  }
  if (fields && (!record || fields.some(key => typeof record[key] !== "boolean"))) {
    throw new Error(`Invalid result for ${operation}`);
  }
  return value as Operations[K]["output"];
}
