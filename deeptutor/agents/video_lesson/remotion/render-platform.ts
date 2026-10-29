// Pure-JavaScript platform support for React's streaming renderer inside QuickJS.
// These objects live entirely in guest memory; none bridges to the host runtime.
import "fast-text-encoding";
import {ReadableStream} from "web-streams-polyfill";
const started = Date.now();
Object.assign(globalThis, {
  performance: {now: () => Date.now() - started},
  ReadableStream,
  console: {log() {}, warn() {}, error() {}, info() {}, debug() {}},
  queueMicrotask: (callback: () => void) => Promise.resolve().then(callback),
  // Frame checks don't wait for real-world I/O. React scheduling runs on the
  // guest promise queue, which the interpreter pumps under the same deadline.
  setTimeout: (callback: () => void) => {
    const timer = {cancelled: false};
    Promise.resolve().then(() => { if (!timer.cancelled) callback(); });
    return timer;
  },
  clearTimeout: (timer: {cancelled: boolean}) => { if (timer) timer.cancelled = true; },
});
