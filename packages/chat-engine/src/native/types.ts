import type { LoopConfig, LoopState } from "../core/contracts.js";
import { validateConfig } from "../core/contracts.js";

export type JsonRecord = Record<string, unknown>;
export interface Message extends JsonRecord {
  role: string;
  content?: unknown;
}
export interface ToolCall {
  id: string;
  name: string;
  arguments: string;
}
export interface ToolSchema {
  type: "function";
  function: { name: string; description?: string; parameters: JsonRecord };
}
export interface ToolSpec {
  schema: ToolSchema;
  sensitive: string[];
  native: boolean;
}
export interface ProviderConfig {
  endpoint: string;
  apiKey: string;
  headers: Record<string, string>;
  model: string;
  format: "chat_completions";
  completion: JsonRecord;
  stream: boolean;
  maxConcurrency: number;
  requestsPerMinute: number;
  retryDelaysMs?: number[];
}
export interface ContextSeed {
  system: string;
  history: Message[];
  snapshots: Record<string, string>;
  user: Message;
  contextWindow: number;
  outputTokens: number;
  model: string;
  route: JsonRecord;
}
export interface NativeInput {
  config: LoopConfig;
  provider: ProviderConfig;
  seed: ContextSeed;
  tools: ToolSpec[];
  toolRuntime?: Record<
    string,
    {
      provider?: ProviderConfig;
      system?: string;
      context?: string;
      sources?: Record<string, string>;
      memoryRoots?: string[];
    }
  >;
  source: string;
  stage: string;
  sessionId: string;
  workspace: { root: string; id: string } | null;
  skillRoots: Record<string, string>;
  rebindingTools: string[];
  deferOutput: boolean;
  policyHooks: boolean;
  userInputEnabled?: boolean;
  initialToolChoice: string | null;
  copy: Record<string, string>;
}
export interface EngineEvent {
  type: string;
  content: string;
  metadata: JsonRecord;
}
export type Emit = (event: EngineEvent) => Promise<void>;
/** Transitional effects only: domain policy, application checkpoints, and unmigrated tools. */
export type LegacyPort = (
  operation: string,
  input: JsonRecord,
) => Promise<unknown>;
export interface Round {
  text: string;
  reasoning: string;
  toolCalls: ToolCall[];
  usage: JsonRecord;
  finishReason: string;
  trace: JsonRecord;
  deferred: EngineEvent[];
  requestTools: ToolSchema[];
}
export interface ToolResult {
  content: string;
  success: boolean;
  metadata: JsonRecord;
  sources: JsonRecord[];
  pause: JsonRecord | null;
  terminate: boolean;
  modelMessage: Message | null;
  usage?: JsonRecord;
}
export interface Dispatch {
  messages: Message[];
  modelMessages: Message[];
  sources: JsonRecord[];
  metadataById: Record<string, JsonRecord>;
  pause: { callId: string; name: string; payload: JsonRecord } | null;
  terminate: { name: string; content: string; metadata: JsonRecord } | null;
  usage?: JsonRecord[];
}
export interface NativeResult {
  state: LoopState;
  response: string;
  completed: boolean;
  sources: JsonRecord[];
  contextBudget: JsonRecord;
  usage: JsonRecord[];
  nativeToolCalls: number;
  legacyToolCalls: number;
}

export function record(value: unknown): JsonRecord {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Expected an object");
  return value as JsonRecord;
}

export function validateProvider(value: unknown): ProviderConfig {
  const provider = record(value);
  if (
    provider.format !== "chat_completions" ||
    typeof provider.endpoint !== "string" ||
    typeof provider.model !== "string" ||
    typeof provider.apiKey !== "string" ||
    typeof provider.stream !== "boolean"
  )
    throw new Error("Invalid provider configuration");
  const endpoint = new URL(provider.endpoint);
  if (
    !["http:", "https:"].includes(endpoint.protocol) ||
    endpoint.username ||
    endpoint.password
  )
    throw new Error("Invalid provider endpoint");
  if (
    Object.values(record(provider.headers)).some((v) => typeof v !== "string")
  )
    throw new Error("Invalid provider headers");
  record(provider.completion);
  if (
    provider.retryDelaysMs !== undefined &&
    (!Array.isArray(provider.retryDelaysMs) ||
      provider.retryDelaysMs.length > 10 ||
      provider.retryDelaysMs.some(
        (x) =>
          typeof x !== "number" || !Number.isFinite(x) || x < 0 || x > 300000,
      ))
  )
    throw new Error("Invalid retry policy");
  return provider as unknown as ProviderConfig;
}

export function validateToolRuntime(
  value: unknown,
): NonNullable<NativeInput["toolRuntime"]> {
  const runtime = record(value);
  for (const item of Object.values(runtime)) {
    const config = record(item);
    if (config.provider !== undefined) validateProvider(config.provider);
    if (
      config.memoryRoots !== undefined &&
      (!Array.isArray(config.memoryRoots) ||
        config.memoryRoots.length > 2 ||
        config.memoryRoots.some((x) => typeof x !== "string"))
    )
      throw new Error("Invalid memory admission");
    for (const key of ["system", "context"])
      if (config[key] !== undefined && typeof config[key] !== "string")
        throw new Error("Invalid model tool context");
    if (
      config.sources !== undefined &&
      Object.values(record(config.sources)).some((v) => typeof v !== "string")
    )
      throw new Error("Invalid source admission");
  }
  return runtime as NonNullable<NativeInput["toolRuntime"]>;
}

export function validateNativeInput(value: unknown): NativeInput {
  const x = record(value),
    provider = validateProvider(x.provider),
    seed = record(x.seed);
  validateConfig(x.config);
  if (x.toolRuntime !== undefined) validateToolRuntime(x.toolRuntime);
  if (
    provider.format !== "chat_completions" ||
    typeof provider.endpoint !== "string" ||
    typeof provider.model !== "string" ||
    typeof provider.apiKey !== "string" ||
    !Array.isArray(x.tools) ||
    !Array.isArray(seed.history) ||
    typeof seed.system !== "string" ||
    !Number.isSafeInteger(seed.contextWindow) ||
    Number(seed.contextWindow) < 1 ||
    !Number.isSafeInteger(seed.outputTokens) ||
    Number(seed.outputTokens) < 1
  )
    throw new Error("Invalid native turn configuration");
  const endpoint = new URL(provider.endpoint);
  if (
    !["http:", "https:"].includes(endpoint.protocol) ||
    endpoint.username ||
    endpoint.password
  )
    throw new Error("Invalid provider endpoint");
  record(provider.headers);
  record(provider.completion);
  record(seed.snapshots);
  record(seed.user);
  for (const name of ["source", "stage", "sessionId"])
    if (typeof x[name] !== "string") throw new Error("Invalid turn identity");
  for (const name of ["deferOutput", "policyHooks"])
    if (typeof x[name] !== "boolean") throw new Error("Invalid turn policy");
  if (
    !Array.isArray(x.rebindingTools) ||
    x.rebindingTools.some((name) => typeof name !== "string")
  )
    throw new Error("Invalid rebinding admission");
  for (const map of [x.skillRoots, x.copy, seed.snapshots, provider.headers])
    if (Object.values(record(map)).some((value) => typeof value !== "string"))
      throw new Error("Invalid string map");
  if (x.workspace !== null) {
    const workspace = record(x.workspace);
    if (typeof workspace.root !== "string" || typeof workspace.id !== "string")
      throw new Error("Invalid workspace admission");
  }
  for (const raw of x.tools) {
    const spec = record(raw),
      fn = record(record(spec.schema).function);
    if (
      typeof fn.name !== "string" ||
      !Array.isArray(spec.sensitive) ||
      typeof spec.native !== "boolean"
    )
      throw new Error("Invalid tool admission");
    record(fn.parameters);
  }
  return x as unknown as NativeInput;
}
