import test from "node:test";
import assert from "node:assert/strict";

import { copyText } from "../lib/clipboard";

type GlobalName = "navigator" | "window" | "document";

/**
 * `globalThis.navigator` is an accessor on modern Node, so a plain assignment
 * throws. Define the property instead, and restore the original descriptor
 * afterwards so one case cannot leak into the next.
 */
function setGlobal(name: GlobalName, value: unknown): () => void {
  const previous = Object.getOwnPropertyDescriptor(globalThis, name);
  Object.defineProperty(globalThis, name, {
    value,
    configurable: true,
    writable: true,
  });
  return () => {
    if (previous) Object.defineProperty(globalThis, name, previous);
    else delete (globalThis as Record<string, unknown>)[name];
  };
}

/**
 * Stand in for the three browser objects `copyText` touches. Each field is
 * optional so a case can model an environment where one is simply absent —
 * which is the whole point: on a plain-http origin `navigator.clipboard` does
 * not exist.
 */
function withBrowser(
  parts: {
    clipboard?: { writeText: (text: string) => Promise<void> };
    isSecureContext?: boolean;
    execCommand?: (command: string) => boolean;
  },
  run: () => Promise<void>,
): Promise<void> {
  const appended: unknown[] = [];
  const restore = [
    setGlobal("navigator", parts.clipboard ? { clipboard: parts.clipboard } : {}),
    setGlobal("window", { isSecureContext: parts.isSecureContext ?? false }),
    setGlobal(
      "document",
      parts.execCommand
        ? {
            activeElement: null,
            body: { appendChild: (node: unknown) => void appended.push(node) },
            createElement: () => ({
              value: "",
              style: {},
              setAttribute: () => undefined,
              select: () => undefined,
              setSelectionRange: () => undefined,
              remove: () => undefined,
            }),
            execCommand: parts.execCommand,
          }
        : undefined,
    ),
  ];

  return run().finally(() => {
    for (const undo of restore.reverse()) undo();
  });
}

test("copyText rejects when there is nothing to copy", async () => {
  await assert.rejects(() => copyText("   "), /nothing to copy/i);
});

test("copyText uses the async Clipboard API in a secure context", async () => {
  const written: string[] = [];
  await withBrowser(
    {
      clipboard: {
        writeText: async (text: string) => void written.push(text),
      },
      isSecureContext: true,
      execCommand: () => {
        throw new Error("the selection fallback must not run here");
      },
    },
    async () => {
      await copyText("eigenvectors");
    },
  );
  assert.deepEqual(written, ["eigenvectors"]);
});

/**
 * The reported bug: reaching a DeepTutor instance over the LAN means a
 * plain-http origin, where `navigator.clipboard` is undefined. The old code
 * threw a TypeError here, swallowed it, and rendered 已复制 anyway.
 */
test("copyText falls back to the selection path on an insecure origin", async () => {
  const commands: string[] = [];
  await withBrowser(
    {
      isSecureContext: false,
      execCommand: (command: string) => {
        commands.push(command);
        return true;
      },
    },
    async () => {
      await copyText("eigenvectors");
    },
  );
  assert.deepEqual(commands, ["copy"]);
});

test("copyText rejects when neither path can write", async () => {
  await withBrowser(
    { isSecureContext: false, execCommand: () => false },
    async () => {
      await assert.rejects(() => copyText("eigenvectors"), /not available/i);
    },
  );
});

/** A rejected `writeText` (lost focus, denied permission) still gets one try. */
test("copyText falls back when the async API rejects", async () => {
  const commands: string[] = [];
  await withBrowser(
    {
      clipboard: {
        writeText: async () => {
          throw new Error("Document is not focused");
        },
      },
      isSecureContext: true,
      execCommand: (command: string) => {
        commands.push(command);
        return true;
      },
    },
    async () => {
      await copyText("eigenvectors");
    },
  );
  assert.deepEqual(commands, ["copy"]);
});
