import { defineConfig, devices } from "@playwright/test";

const BASE_URL =
  process.env.WEB_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:3000";
const SERIAL_MODE = process.env.PW_SERIAL === "1";

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
  projects: [
    {
      name: "ui-audit",
      testMatch: "**/*.audit.ts",
      testIgnore: [
        "**/epub-reader.audit.ts",
        "**/e2e/turn-lifecycle.audit.ts",
        "**/e2e/multi-worker-turns.audit.ts",
      ],
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "critical-turns",
      testMatch: "**/e2e/turn-lifecycle.audit.ts",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "multi-worker-turns-desktop",
      testMatch: "**/e2e/multi-worker-turns.audit.ts",
      use: { ...devices["Desktop Chrome"], reducedMotion: "reduce" },
    },
    {
      name: "multi-worker-turns-mobile",
      testMatch: "**/e2e/multi-worker-turns.audit.ts",
      use: { ...devices["iPhone 13"], reducedMotion: "reduce" },
    },
    {
      name: "epub-reader-chromium",
      testMatch: "**/epub-reader.audit.ts",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "epub-reader-webkit",
      testMatch: "**/epub-reader.audit.ts",
      use: { ...devices["iPhone 13"] },
    },
  ],
});
