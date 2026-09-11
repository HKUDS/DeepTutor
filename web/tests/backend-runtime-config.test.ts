import assert from "node:assert/strict";
import test from "node:test";

import { resolveBackendApiBase } from "../lib/backend-runtime-config";

test("backend proxy prefers the private server-side origin", () => {
  assert.equal(
    resolveBackendApiBase({
      DEEPTUTOR_API_BASE_URL: "http://backend.internal:9000",
      BACKEND_PORT: "8123",
      NEXT_PUBLIC_API_BASE: "https://api.example.com",
    }),
    "http://backend.internal:9000",
  );
});

test("backend proxy follows the launcher's resolved local port", () => {
  assert.equal(
    resolveBackendApiBase({ BACKEND_PORT: "8123" }),
    "http://127.0.0.1:8123",
  );
});

test("backend proxy survives Next workers that retain only managed env", () => {
  assert.equal(
    resolveBackendApiBase({ NEXT_PUBLIC_API_BASE: "http://localhost:8000" }),
    "http://localhost:8000",
  );
});

test("backend proxy keeps the legacy default for a bare frontend start", () => {
  assert.equal(resolveBackendApiBase({}), "http://127.0.0.1:8001");
});
