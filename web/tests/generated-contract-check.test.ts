import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const contract = "export interface Example { value: string; }\n";

function writeFixtureFile(root: string, relativePath: string, content: string): void {
  const destination = path.join(root, relativePath);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, content);
}

function checkContracts(lineEnding: "\n" | "\r\n", stale: boolean): void {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "deeptutor-contract-check-test-"));
  try {
    writeFixtureFile(root, "package.json", JSON.stringify({ type: "module" }));
    writeFixtureFile(
      root,
      "scripts/generate-contracts.mjs",
      fs.readFileSync(path.resolve("scripts/generate-contracts.mjs"), "utf8"),
    );
    writeFixtureFile(
      root,
      "node_modules/prettier/package.json",
      JSON.stringify({ type: "module", exports: "./index.js" }),
    );
    writeFixtureFile(
      root,
      "node_modules/prettier/index.js",
      "export async function format(source) { return source; }\n",
    );
    const generator =
      "import fs from 'node:fs'; " +
      `fs.writeFileSync(process.argv[process.argv.indexOf('--output') + 1], ${JSON.stringify(contract)});\n`;
    for (const relativePath of [
      "node_modules/openapi-typescript/bin/cli.js",
      "node_modules/json-schema-to-typescript/dist/src/cli.js",
    ]) {
      writeFixtureFile(root, relativePath, generator);
    }
    const checkedIn = (stale ? contract.replace("string", "number") : contract).replaceAll(
      "\n",
      lineEnding,
    );
    for (const name of ["api.ts", "turn-protocol.ts"]) {
      writeFixtureFile(root, `contracts/generated/${name}`, checkedIn);
    }

    const result = spawnSync(process.execPath, ["scripts/generate-contracts.mjs", "--check"], {
      cwd: root,
      encoding: "utf8",
    });

    assert.equal(result.status, stale ? 1 : 0, result.stderr);
    if (stale) {
      assert.match(result.stderr, /Generated contract is stale: contracts\/generated\/api\.ts/);
      assert.match(result.stderr, /Generated contract is stale: contracts\/generated\/turn-protocol\.ts/);
    }
    for (const name of ["api.ts", "turn-protocol.ts"]) {
      assert.equal(fs.readFileSync(path.join(root, "contracts/generated", name), "utf8"), checkedIn);
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

for (const [label, lineEnding] of [
  ["LF", "\n"],
  ["CRLF", "\r\n"],
] as const) {
  test(`contract check accepts matching ${label} files without rewriting them`, () => {
    checkContracts(lineEnding, false);
  });
  test(`contract check rejects semantic drift in ${label} files without rewriting them`, () => {
    checkContracts(lineEnding, true);
  });
}
