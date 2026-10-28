/** Evaluate a self-contained JS expression in a capability-free WebAssembly VM.
 *
 * The expression may return a string or a Promise<string>. Only the result string
 * crosses the boundary: no host callbacks, module loader, Node/browser objects,
 * filesystem, environment, sockets or subprocess APIs are registered. Function()
 * and eval stay inside the guest. This is separate from shell sandbox selection:
 * a language VM does not grant permission to execute arbitrary host commands.
 *
 * The caller owns a disposable subprocess for a hard wall-clock deadline and
 * cancellation. Interpreter limits also bound guest memory, stack and execution.
 */
export async function evaluateJavaScript(QuickJS, source, {
  timeoutMs = 180000,
  memoryLimitBytes = 128 * 1024 * 1024,
  maxOutputChars = 64000,
} = {}) {
  const runtime = QuickJS.newRuntime();
  runtime.setMemoryLimit(memoryLimitBytes);
  runtime.setMaxStackSize(1024 * 1024);
  const deadline = Date.now() + timeoutMs;
  runtime.setInterruptHandler(() => Date.now() >= deadline);
  const context = runtime.newContext();
  let handle;
  const unwrap = (result) => {
    if (result.error) {
      // Error serialization also executes only in the bounded guest interpreter.
      const error = context.dump(result.error);
      result.error.dispose();
      throw new Error(error?.message || String(error));
    }
    return result.value;
  };
  try {
    handle = unwrap(context.evalCode(source, "sandbox.js"));
    while (true) {
      if (Date.now() >= deadline) throw new Error("JavaScript execution timed out");
      const state = context.getPromiseState(handle);
      if (state.type === "rejected") {
        const error = context.dump(state.error);
        state.error.dispose();
        throw new Error(error?.message || String(error));
      }
      if (state.type === "fulfilled") {
        try {
          if (context.typeof(state.value) !== "string") throw new Error("Sandbox must return a string");
          const length = context.getProp(state.value, "length");
          try {
            if (context.getNumber(length) > maxOutputChars) throw new Error("Sandbox output limit exceeded");
          } finally {
            length.dispose();
          }
          return context.getString(state.value);
        } finally {
          if (!state.notAPromise) state.value.dispose();
        }
      }
      if (!runtime.hasPendingJob()) throw new Error("Sandbox promise did not settle");
      const jobs = runtime.executePendingJobs(1);
      if (jobs.error) {
        const error = context.dump(jobs.error);
        jobs.error.dispose();
        throw new Error(error?.message || String(error));
      }
    }
  } finally {
    handle?.dispose();
    context.dispose();
    runtime.dispose();
  }
}
