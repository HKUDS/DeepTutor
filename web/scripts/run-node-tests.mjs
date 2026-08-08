import {
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  statSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const webRoot = path.resolve(__dirname, "..");
const cacheRoot = path.join(webRoot, "node_modules", ".cache");
mkdirSync(cacheRoot, { recursive: true });
const distRoot = mkdtempSync(path.join(cacheRoot, "deeptutor-node-tests-"));
const testRoot = path.join(distRoot, "tests");

function cleanupDistRoot() {
  rmSync(distRoot, { recursive: true, force: true });
}

process.once("exit", cleanupDistRoot);
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => {
    cleanupDistRoot();
    process.kill(process.pid, signal);
  });
}

function run(cmd, args, env = process.env) {
  const result = spawnSync(cmd, args, {
    cwd: webRoot,
    stdio: "inherit",
    env,
  });
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function collectTests(dir) {
  const entries = readdirSync(dir)
    .map((name) => path.join(dir, name))
    .sort((a, b) => a.localeCompare(b));
  const files = [];
  for (const entry of entries) {
    const stats = statSync(entry);
    if (stats.isDirectory()) {
      files.push(...collectTests(entry));
      continue;
    }
    if (entry.endsWith(".test.js")) {
      files.push(entry);
    }
  }
  return files;
}

run(process.execPath, [
  path.join(webRoot, "node_modules", "typescript", "bin", "tsc"),
  "-p",
  "tsconfig.node-tests.json",
  "--outDir",
  distRoot,
]);

const testFiles = collectTests(testRoot);
if (testFiles.length === 0) {
  console.error("No compiled node tests found.");
  process.exit(1);
}

run(
  process.execPath,
  [
    "-r",
    "./scripts/register-node-test-aliases.cjs",
    "--test",
    ...testFiles,
  ],
  { ...process.env, DEEPTUTOR_NODE_TESTS_DIST_ROOT: distRoot },
);

cleanupDistRoot();
