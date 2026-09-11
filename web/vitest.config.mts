import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const webRoot = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      "@": webRoot,
    },
  },
  test: {
    environment: "jsdom",
    environmentOptions: {
      jsdom: { url: "http://localhost/" },
    },
    setupFiles: ["./tests/setup/rendered.ts"],
    include: ["tests/**/*.spec.ts", "tests/**/*.spec.tsx"],
    clearMocks: true,
    restoreMocks: true,
  },
});
