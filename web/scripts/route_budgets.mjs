import fs from "fs";
import path from "path";
import vm from "vm";

const APP_SERVER_DIR = path.resolve(".next/server/app");
const APP_OUTPUT_DIR = path.resolve(".next");

const ROUTE_BUDGETS_KB = {
  "/": 700,
  "/playground": 700,
  "/co-writer": 200,
  "/co-writer/[docId]": 700,
  "/knowledge": 450,
  "/memory": 450,
  "/settings": 180,
};

const ROOT_SHELL_BUDGET_KB = 220;

function walkManifestFiles(rootDir) {
  const entries = [];
  for (const item of fs.readdirSync(rootDir, { withFileTypes: true })) {
    const fullPath = path.join(rootDir, item.name);
    if (item.isDirectory()) {
      entries.push(...walkManifestFiles(fullPath));
      continue;
    }
    if (item.name.endsWith("_client-reference-manifest.js")) {
      entries.push(fullPath);
    }
  }
  return entries.sort();
}

function evaluateManifest(filePath) {
  const context = { globalThis: { __RSC_MANIFEST: {} } };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(filePath, "utf8"), context);
  const manifestEntries = Object.entries(context.globalThis.__RSC_MANIFEST);
  if (manifestEntries.length !== 1) {
    throw new Error(`Expected exactly one manifest in ${filePath}`);
  }
  const [manifestKey, manifest] = manifestEntries[0];
  return { manifestKey, manifest };
}

function normalizePublicRoute(manifestKey) {
  const withoutGroups = manifestKey.replace(/\/\([^/]+\)/g, "");
  const withoutPageSuffix = withoutGroups.replace(/\/page$/, "");
  return withoutPageSuffix || "/";
}

function resolveChunkSize(chunkPath) {
  const filePath = path.join(APP_OUTPUT_DIR, chunkPath.replace(/^\/+/, ""));
  return fs.existsSync(filePath) ? fs.statSync(filePath).size : 0;
}

function sumChunkSizes(chunkPaths) {
  return chunkPaths.reduce((total, chunkPath) => total + resolveChunkSize(chunkPath), 0);
}

if (!fs.existsSync(APP_SERVER_DIR)) {
  console.error("Missing .next/server/app. Run `npm run build` before `npm run perf:check`.");
  process.exit(1);
}

const manifestFiles = walkManifestFiles(APP_SERVER_DIR).filter(
  (filePath) => !filePath.includes("_global-error") && !filePath.includes("_not-found"),
);

const routeRows = [];
let rootShellSize = 0;

for (const manifestFile of manifestFiles) {
  const { manifestKey, manifest } = evaluateManifest(manifestFile);
  const route = normalizePublicRoute(manifestKey);
  const entryFiles = manifest.entryJSFiles;

  const rootLayoutFiles = entryFiles["[project]/app/layout"] || [];
  if (!rootShellSize && rootLayoutFiles.length > 0) {
    rootShellSize = sumChunkSizes(rootLayoutFiles);
  }
  const rootLayoutChunks = new Set(rootLayoutFiles);

  const routeEntryKey = Object.keys(entryFiles).find(
    (key) => key.startsWith("[project]/app/") && key.endsWith("/page") && !key.includes("/layout"),
  );
  if (!routeEntryKey) {
    continue;
  }

  const chunkPaths = (entryFiles[routeEntryKey] || []).filter(
    (chunkPath) => !rootLayoutChunks.has(chunkPath),
  );
  routeRows.push({
    route,
    sizeBytes: sumChunkSizes(chunkPaths),
    chunks: chunkPaths.map((chunkPath) => path.basename(chunkPath)),
  });
}

let hasFailure = false;

console.log("Route budgets (excluding root shell):");
for (const row of routeRows) {
  const sizeKb = Math.round(row.sizeBytes / 1024);
  const budget = ROUTE_BUDGETS_KB[row.route];
  const status = budget && sizeKb > budget ? "FAIL" : "OK";
  if (status === "FAIL") {
    hasFailure = true;
  }
  console.log(
    `${status.padEnd(4)} ${row.route.padEnd(12)} ${String(sizeKb).padStart(4)}KB` +
      (budget ? ` / budget ${budget}KB` : ""),
  );
}

if (rootShellSize) {
  const rootShellKb = Math.round(rootShellSize / 1024);
  const rootStatus = rootShellKb > ROOT_SHELL_BUDGET_KB ? "FAIL" : "OK";
  if (rootStatus === "FAIL") {
    hasFailure = true;
  }
  console.log(
    `${rootStatus.padEnd(4)} ${"root-shell".padEnd(12)} ${String(rootShellKb).padStart(4)}KB / budget ${ROOT_SHELL_BUDGET_KB}KB`,
  );
}

if (hasFailure) {
  process.exit(1);
}
