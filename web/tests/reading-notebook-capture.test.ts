import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

function source(file: string): string {
  return fs.readFileSync(path.resolve(process.cwd(), file), "utf8");
}

test("save to notebook posts to the backend's workspace notebook route", () => {
  const client = source("lib/reading-workspace-api.ts");
  const fn = client.slice(
    client.indexOf("export async function sendReadingToNotebook"),
  );
  const match = fn.match(/json\(`(\/workspaces\/\$\{workspaceId\}\/[^`]+)`/);
  assert.ok(match, "sendReadingToNotebook should call json() with a path");

  const route = `/api/reading${match[1].replace("${workspaceId}", "{workspace_id}")}`;
  assert.ok(
    source("contracts/generated/api.ts").includes(`"${route}":`),
    `${route} is not a backend route`,
  );
});
