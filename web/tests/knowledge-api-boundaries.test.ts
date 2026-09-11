import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = process.cwd();
const sourceRoots = ["app", "components", "features", "hooks", "lib", "tests"];

function filesBelow(relativeRoot: string): string[] {
  const result: string[] = [];
  const visit = (directory: string) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(target);
      else if (/\.(?:ts|tsx)$/.test(entry.name)) result.push(target);
    }
  };
  visit(path.join(root, relativeRoot));
  return result;
}

test("knowledge callers use resource clients instead of the retired barrel", () => {
  assert.equal(fs.existsSync(path.join(root, "lib/knowledge-api.ts")), false);
  const violations = sourceRoots
    .flatMap(filesBelow)
    .filter((file) =>
      /from\s+["'][^"']*lib\/knowledge-api["']/.test(
        fs.readFileSync(file, "utf8"),
      ),
    )
    .map((file) => path.relative(root, file));
  assert.deepEqual(violations, []);
});

test("knowledge resources expose narrow public entry points", () => {
  const apiRoot = path.join(root, "features/knowledge/api");
  const expected = {
    "catalog.ts": ["listKnowledgeBases", "createKnowledgeBase"],
    "engines.ts": ["getEnginePreflight", "updateLlamaIndexConfig"],
    "files.ts": ["listKnowledgeBaseFiles", "knowledgeBaseFilePath"],
    "sources.ts": ["listGitHubSources", "syncWebSources"],
  };

  for (const [filename, exports] of Object.entries(expected)) {
    const source = fs.readFileSync(path.join(apiRoot, filename), "utf8");
    for (const name of exports)
      assert.match(source, new RegExp(`\\b${name}\\b`));
  }
});

test("engine forms have stable feature-owned module boundaries", () => {
  const formsRoot = path.join(root, "features/knowledge/components/engines");
  for (const name of [
    "LlamaIndexForm",
    "GraphRagForm",
    "LightRagForm",
    "ImaForm",
  ]) {
    const filename = path.join(formsRoot, `${name}.tsx`);
    assert.equal(fs.existsSync(filename), true);
    assert.match(
      fs.readFileSync(filename, "utf8"),
      new RegExp(`\\b${name}\\b`),
    );
  }
});
