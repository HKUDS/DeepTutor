import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const source = readFileSync(
  path.resolve(process.cwd(), "components/partners/PartnerChat.tsx"),
  "utf8",
);

function escapeStopEffect(): string {
  const sendStopStart = source.indexOf("const sendStop = useCallback");
  const commandStart = source.indexOf(
    "// Session-management commands",
    sendStopStart,
  );

  assert.notEqual(sendStopStart, -1, "sendStop callback should exist");
  assert.notEqual(commandStart, -1, "client command handler should follow");
  return source.slice(sendStopStart, commandStart);
}

test("partner chat listens for Escape only while streaming", () => {
  const effect = escapeStopEffect();

  assert.match(effect, /useEffect\(\(\) => \{/);
  assert.match(effect, /if \(!streaming\) return;/);
  assert.match(effect, /if \(event\.key !== "Escape"\) return;/);
  assert.match(effect, /sendStop\(\);/);
  assert.match(effect, /\}, \[streaming, sendStop\]\);/);
});

test("partner chat removes its streaming Escape listener", () => {
  const effect = escapeStopEffect();

  assert.match(effect, /window\.addEventListener\("keydown", onKeyDown\);/);
  assert.match(
    effect,
    /return \(\) => window\.removeEventListener\("keydown", onKeyDown\);/,
  );
});
