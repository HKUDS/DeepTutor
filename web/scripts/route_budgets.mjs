import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const NEXT_OUTPUT_DIR = path.join(WEB_ROOT, ".next");
const BUILD_MANIFEST_PATH = path.join(NEXT_OUTPUT_DIR, "build-manifest.json");
const NEXT_BIN = path.join(WEB_ROOT, "node_modules", "next", "dist", "bin", "next");

const ROUTE_TARGETS = [
  { route: "/", requestPath: "/", budgetKb: 300 },
  { route: "/chat/[sessionId]", requestPath: "/chat/perf-budget", budgetKb: 1_020 },
  { route: "/settings", requestPath: "/settings", budgetKb: 840 },
  { route: "/knowledge-bases", requestPath: "/knowledge-bases", budgetKb: 540 },
  { route: "/co-writer", requestPath: "/co-writer", budgetKb: 320 },
  { route: "/co-writer/[docId]", requestPath: "/co-writer/perf-budget", budgetKb: 515 },
  {
    route: "/reading/[workspaceId]/sessions/[sessionId]",
    requestPath: "/reading/perf-budget/sessions/perf-session",
    budgetKb: 1_120,
  },
  {
    route: "/mastery/[pathId]/sessions/[sessionId]",
    requestPath: "/mastery/perf-budget/sessions/perf-session",
    budgetKb: 980,
  },
];

const ROOT_SHELL_BUDGET_KB = 390;
const SERVER_TIMEOUT_MS = 20_000;

function assertBuildPresent() {
  if (!fs.existsSync(BUILD_MANIFEST_PATH)) {
    throw new Error("Missing .next build output. Run `npm run build` before `npm run perf:check`.");
  }
}

function findAvailablePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

async function waitForServer(baseUrl, processState) {
  const deadline = Date.now() + SERVER_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (processState.exited) {
      throw new Error(`Next server exited before readiness:\n${processState.output}`);
    }
    try {
      const response = await fetch(`${baseUrl}/login`);
      if (response.ok) return;
    } catch {
      // Startup races are expected until the listener is ready.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for the production server:\n${processState.output}`);
}

async function startBuildServer() {
  const port = await findAvailablePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const child = spawn(
    process.execPath,
    [NEXT_BIN, "start", "--hostname", "127.0.0.1", "--port", String(port)],
    {
      cwd: WEB_ROOT,
      env: {
        ...process.env,
        NEXT_TELEMETRY_DISABLED: "1",
        DEEPTUTOR_API_BASE_URL: "http://127.0.0.1:9",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const state = { exited: false, output: "" };
  const capture = (chunk) => {
    state.output = `${state.output}${String(chunk)}`.slice(-8_000);
  };
  child.stdout.on("data", capture);
  child.stderr.on("data", capture);
  child.once("exit", () => {
    state.exited = true;
  });
  await waitForServer(baseUrl, state);
  return { baseUrl, child };
}

function scriptChunks(html, baseUrl) {
  const chunks = new Set();
  for (const match of html.matchAll(/<script[^>]+src="([^"]+\.js(?:\?[^\"]*)?)"/g)) {
    const pathname = decodeURIComponent(new URL(match[1], baseUrl).pathname);
    const relative = pathname.replace(/^\/_next\//, "");
    if (relative.startsWith("static/") && relative.endsWith(".js")) chunks.add(relative);
  }
  return chunks;
}

async function loadRouteChunks(baseUrl, requestPath) {
  const response = await fetch(`${baseUrl}${requestPath}`);
  if (!response.ok) {
    throw new Error(`${requestPath} returned HTTP ${response.status} during route measurement`);
  }
  return scriptChunks(await response.text(), baseUrl);
}

function intersection(sets) {
  if (sets.length === 0) return new Set();
  return sets.slice(1).reduce(
    (shared, current) => new Set([...shared].filter((item) => current.has(item))),
    new Set(sets[0]),
  );
}

function difference(source, ...excludedSets) {
  const excluded = new Set(excludedSets.flatMap((items) => [...items]));
  return new Set([...source].filter((item) => !excluded.has(item)));
}

function chunkSize(chunkPath) {
  const filePath = path.join(NEXT_OUTPUT_DIR, chunkPath);
  if (!fs.existsSync(filePath)) {
    throw new Error(`Build HTML references missing client chunk ${chunkPath}`);
  }
  return fs.statSync(filePath).size;
}

function sumChunkSizes(chunks) {
  return [...chunks].reduce((total, chunk) => total + chunkSize(chunk), 0);
}

function kb(bytes) {
  return Math.round(bytes / 1024);
}

function printRow(label, sizeKb, budgetKb) {
  const failed = sizeKb > budgetKb;
  console.log(
    `${(failed ? "FAIL" : "OK").padEnd(4)} ${label.padEnd(47)} ${String(sizeKb).padStart(4)}KB / budget ${budgetKb}KB`,
  );
  return failed;
}

async function main() {
  assertBuildPresent();
  const buildManifest = JSON.parse(fs.readFileSync(BUILD_MANIFEST_PATH, "utf8"));
  const frameworkChunks = new Set([
    ...(buildManifest.rootMainFiles || []),
    ...(buildManifest.polyfillFiles || []),
  ]);
  const server = await startBuildServer();

  try {
    const rows = [];
    for (const target of ROUTE_TARGETS) {
      rows.push({ ...target, chunks: await loadRouteChunks(server.baseUrl, target.requestPath) });
    }
    // Auth uses the root layout but neither utility nor workspace layout, so
    // it prevents feature shells from being misclassified as the root shell.
    const authChunks = await loadRouteChunks(server.baseUrl, "/login");
    const appShellChunks = difference(
      intersection([...rows.map((row) => row.chunks), authChunks]),
      frameworkChunks,
    );

    console.log("Route budgets (raw production JS; framework and root app shell excluded):");
    let failed = false;
    for (const row of rows) {
      const routeChunks = difference(row.chunks, frameworkChunks, appShellChunks);
      failed = printRow(row.route, kb(sumChunkSizes(routeChunks)), row.budgetKb) || failed;
    }
    failed =
      printRow("root-app-shell", kb(sumChunkSizes(appShellChunks)), ROOT_SHELL_BUDGET_KB) || failed;

    if (failed) process.exitCode = 1;
  } finally {
    server.child.kill("SIGTERM");
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
