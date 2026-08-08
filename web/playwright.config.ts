import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const BASE_URL =
  process.env.WEB_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:3000";
const SERIAL_MODE = process.env.PW_SERIAL === "1";
const MANAGE_SERVERS = process.env.PW_MANAGED_SERVERS === "1";
const FUNCTIONAL_BASE_URL = "http://127.0.0.1:3100";
const WEB_ROOT = __dirname;
const REPO_ROOT = resolve(WEB_ROOT, "..");
const E2E_HOME = MANAGE_SERVERS
  ? mkdtempSync(join(tmpdir(), "deeptutor-e2e-"))
  : "";

if (E2E_HOME) {
  const cleanupE2EHome = () => {
    rmSync(E2E_HOME, { force: true, recursive: true });
  };
  process.once("exit", cleanupE2EHome);
  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    process.once(signal, () => {
      cleanupE2EHome();
      process.kill(process.pid, signal);
    });
  }
}

export default defineConfig({
  testDir: "./tests",
  fullyParallel: !SERIAL_MODE,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: SERIAL_MODE ? 1 : undefined,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  webServer: MANAGE_SERVERS
    ? [
        {
          command:
            "uv run --no-sync uvicorn deeptutor.api.main:app --host 127.0.0.1 --port 8101 --no-access-log",
          cwd: REPO_ROOT,
          env: {
            DEEPTUTOR_HOME: E2E_HOME,
            DEEPTUTOR_AUTH_ENABLED: "false",
          },
          url: "http://127.0.0.1:8101/",
          reuseExistingServer: false,
          timeout: 120_000,
        },
        {
          command:
            "bun ./node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3100",
          cwd: WEB_ROOT,
          env: {
            DEEPTUTOR_HOME: E2E_HOME,
            DEEPTUTOR_API_BASE_URL: "http://127.0.0.1:8101",
            DEEPTUTOR_AUTH_ENABLED: "false",
          },
          url: FUNCTIONAL_BASE_URL,
          reuseExistingServer: false,
          timeout: 120_000,
        },
      ]
    : undefined,
  projects: [
    {
      name: "ui-audit",
      testMatch: "**/*.audit.ts",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "functional-e2e",
      testMatch: "**/*.e2e.ts",
      use: {
        ...devices["Desktop Chrome"],
        baseURL: MANAGE_SERVERS ? FUNCTIONAL_BASE_URL : BASE_URL,
      },
    },
  ],
});
