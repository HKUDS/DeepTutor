import { test } from "node:test";
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { validateOutput } from "../src/core/contracts.js";

test("core has no transport, business feature, provider SDK or Node dependency", async () => {
  const root = fileURLToPath(new URL("../../src/", import.meta.url));
  const edges = new Map<string, string[]>();
  const scan = async (folder: string): Promise<void> => {
    for (const entry of await readdir(folder, { withFileTypes: true })) {
      const file = join(folder, entry.name);
      if (entry.isDirectory()) { await scan(file); continue; }
      if (!file.endsWith(".ts")) continue;
      const text = await readFile(file, "utf8");
      const imports = [...text.matchAll(/(?:from\s+|import\s*\()(["'])([^"']+)\1/g)].map(x => x[2]!);
      const local = imports.filter(x => x.startsWith(".")).map(x => resolve(dirname(file), x).replace(/\.js$/, ".ts"));
      edges.set(file, local);
      if (relative(root, file).startsWith("core/")) {
        assert.ok(imports.every(x => x.startsWith("./")), `${file}: core dependencies must remain local`);
        assert.ok(local.every(x => relative(root, x).startsWith("core/")), `${file}: core must not depend on adapters`);
      }
    }
  };
  await scan(root);
  const visited = new Set<string>();
  const visiting = new Set<string>();
  const visit = (file: string) => {
    assert.ok(!visiting.has(file), `Dependency cycle at ${file}`);
    if (visited.has(file)) return;
    visiting.add(file);
    for (const target of edges.get(file) ?? []) visit(target);
    visiting.delete(file); visited.add(file);
  };
  for (const file of edges.keys()) visit(file);
});

test("wire result shapes fail closed instead of spending another model/tool round", () => {
  assert.throws(() => validateOutput("call_round", {}), /Invalid result/);
  assert.throws(() => validateOutput("resolve_pause", "false"), /Invalid pause/);
  assert.throws(() => validateOutput("forced_finish", { extraRounds: 10 }), /Invalid forced/);
  assert.throws(() => validateOutput("raise_reasoning_budget", null), /must terminate/);
});
