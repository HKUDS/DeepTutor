/** Private, versioned parent/child transport. stdout is exclusively protocol. */
import { createInterface } from "node:readline";
import { once } from "node:events";
import { runLoop } from "../core/run-loop.js";
import { HostFailure, validateConfig } from "../core/contracts.js";
import type {
  LoopHost,
  LoopState,
  Operation,
  Operations,
} from "../core/contracts.js";

type Pending = {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
};
type Run = {
  controller: AbortController;
  pending: Map<string, Pending>;
  next: number;
};
const runs = new Map<string, Run>();
const MAX_RUNS = 128;
const MAX_LINE = 48 * 1024 * 1024;
let writing = Promise.resolve();

async function send(message: object): Promise<void> {
  const frame = JSON.stringify({ v: 1, ...message }) + "\n";
  if (Buffer.byteLength(frame) > MAX_LINE)
    throw new Error("Engine frame exceeds limit");
  // Serialize writes, honoring backpressure without interleaving JSON lines.
  writing = writing.then(async () => {
    if (!process.stdout.write(frame)) await once(process.stdout, "drain");
  });
  return writing;
}

function abort(run: Run): void {
  run.controller.abort();
  for (const pending of run.pending.values())
    pending.reject(new Error("Turn cancelled"));
  run.pending.clear();
}

async function execute(
  id: string,
  config: unknown,
  mode: "run" | "native" | "history" | "completion" | "service" = "run",
): Promise<void> {
  if (runs.has(id) || runs.size >= MAX_RUNS) {
    await send({
      kind: "failed",
      runId: id,
      message: "Chat engine capacity or duplicate run",
    });
    return;
  }
  const run: Run = {
    controller: new AbortController(),
    pending: new Map(),
    next: 0,
  };
  runs.set(id, run);
  const host: LoopHost = {
    async invoke<K extends Operation>(
      operation: K,
      input: Operations[K]["input"],
      state: Readonly<LoopState>,
    ): Promise<Operations[K]["output"]> {
      const callId = String(++run.next);
      const response = new Promise<unknown>((resolve, reject) => {
        run.pending.set(callId, { resolve, reject });
      });
      // Attach the handler before a broken pipe or cancellation can reject it.
      const sent = send({
        kind: "call",
        runId: id,
        callId,
        operation,
        input,
        state,
      });
      const [, result] = await Promise.all([sent, response]);
      return result as Operations[K]["output"];
    },
  };
  try {
    const port = (operation: string, input: Record<string, unknown>) =>
      host.invoke(operation as Operation, input as never, {
        rounds: 0,
        exploration_rounds: 0,
        settlement_rounds: 0,
        tool_steps: 0,
        reasoning_budget_recoveries: 0,
      });
    const state =
      mode === "native"
        ? await (
            await import("../native/session.js")
          ).runNative(config, port, run.controller.signal)
        : mode === "history"
          ? await (
              await import("../context/history.js")
            ).planHistory(
              config as import("../context/history.js").HistoryInput,
              port,
              run.controller.signal,
            )
          : mode === "service"
            ? await (
                await import("../providers/service-call.js")
              ).serviceCall(config, port, run.controller.signal)
            : mode === "completion"
              ? await (
                  await import("../providers/one-shot.js")
                ).oneShot(
                  config as Parameters<
                    typeof import("../providers/one-shot.js").oneShot
                  >[0],
                  run.controller.signal,
                )
              : await runLoop(
                  host,
                  validateConfig(config),
                  run.controller.signal,
                );
    await send({ kind: "complete", runId: id, state });
  } catch (error) {
    if (!run.controller.signal.aborted) {
      await send({
        kind: "failed",
        runId: id,
        callId: error instanceof HostFailure ? error.callId : undefined,
        partialResponse:
          mode !== "run" ||
          (error instanceof HostFailure && error.partialResponse),
        message: error instanceof Error ? error.message : "Engine failed",
      });
    }
  } finally {
    abort(run);
    runs.delete(id);
  }
}

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
lines.on("line", (line: string) => {
  try {
    if (Buffer.byteLength(line) > MAX_LINE)
      throw new Error("Oversized engine frame");
    const frame: unknown = JSON.parse(line);
    if (!frame || typeof frame !== "object")
      throw new Error("Invalid engine frame");
    const value = frame as Record<string, unknown>;
    if (
      value.v !== 1 ||
      typeof value.runId !== "string" ||
      value.runId.length > 128
    )
      throw new Error("Invalid engine protocol");
    const run = runs.get(value.runId);
    if (value.kind === "run") void execute(value.runId, value.config);
    else if (
      value.kind === "native" ||
      value.kind === "history" ||
      value.kind === "completion" ||
      value.kind === "service"
    )
      void execute(value.runId, value.input, value.kind);
    else if (value.kind === "cancel") {
      if (run) abort(run);
    } else if (value.kind === "reply") {
      if (typeof value.callId !== "string")
        throw new Error("Invalid call identity");
      const pending = run?.pending.get(value.callId);
      if (!pending) return; // Late reply to a cancelled run.
      run?.pending.delete(value.callId);
      if (value.ok === true) pending.resolve(value.result);
      else {
        const error = value.error as Record<string, unknown> | undefined;
        pending.reject(
          new HostFailure(
            String(error?.message ?? "Host operation failed"),
            value.callId,
            error?.partialResponse === true,
            error?.fatal === true,
          ),
        );
      }
    } else throw new Error("Unknown engine frame");
  } catch {
    // Malformed internal protocol is fatal, never silently replay a turn.
    process.stderr.write("Invalid chat engine protocol frame\n");
    for (const run of runs.values()) abort(run);
    process.exitCode = 1;
    lines.close();
    process.stdin.destroy();
  }
});
lines.on("close", () => {
  for (const run of runs.values()) abort(run);
});
process.stdout.on("error", () => {
  for (const run of runs.values()) abort(run);
  process.exit(1);
});
