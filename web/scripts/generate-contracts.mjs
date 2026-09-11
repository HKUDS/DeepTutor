import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { format } from "prettier";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(scriptDirectory, "..");
const schemaRoot = path.join(webRoot, "contracts", "schema");
const generatedRoot = path.join(webRoot, "contracts", "generated");
const check = process.argv.includes("--check");
const temporaryRoot = mkdtempSync(path.join(tmpdir(), "deeptutor-contracts-"));

const outputs = [
  {
    name: "api.ts",
    command: path.join(webRoot, "node_modules", "openapi-typescript", "bin", "cli.js"),
    args: [
      path.join(schemaRoot, "openapi.json"),
      "--output",
      path.join(temporaryRoot, "api.ts"),
      "--alphabetize",
      "--immutable",
      "--root-types",
    ],
  },
  {
    name: "turn-protocol.ts",
    command: path.join(
      webRoot,
      "node_modules",
      "json-schema-to-typescript",
      "dist",
      "src",
      "cli.js",
    ),
    args: [
      "--input",
      path.join(schemaRoot, "turn-protocol.json"),
      "--output",
      path.join(temporaryRoot, "turn-protocol.ts"),
      "--unknownAny",
      "--unreachableDefinitions",
      "--style.printWidth=100",
    ],
  },
];

let hasDrift = false;

try {
  for (const output of outputs) {
    const result = spawnSync(process.execPath, [output.command, ...output.args], {
      cwd: webRoot,
      encoding: "utf8",
    });
    if (result.status !== 0) {
      process.stderr.write(result.stderr || result.stdout);
      process.exit(result.status ?? 1);
    }

    const target = path.join(generatedRoot, output.name);
    const generated = await format(
      readFileSync(path.join(temporaryRoot, output.name), "utf8"),
      { filepath: target },
    );
    let current = null;
    try {
      current = readFileSync(target, "utf8");
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }

    if (current === generated) continue;
    hasDrift = true;
    if (check) {
      console.error(`Generated contract is stale: contracts/generated/${output.name}`);
      continue;
    }
    mkdirSync(generatedRoot, { recursive: true });
    writeFileSync(target, generated, "utf8");
    console.log(`Updated contracts/generated/${output.name}`);
  }
} finally {
  rmSync(temporaryRoot, { recursive: true, force: true });
}

if (check && hasDrift) process.exit(1);
