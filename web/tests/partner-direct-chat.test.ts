import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const chatSource = readFileSync(
  path.resolve(process.cwd(), "components/partners/PartnerChat.tsx"),
  "utf8",
);
const pageSource = readFileSync(
  path.resolve(process.cwd(), "app/(workspace)/partners/[partnerId]/page.tsx"),
  "utf8",
);
const archiveSource = readFileSync(
  path.resolve(process.cwd(), "components/partners/PartnerArchives.tsx"),
  "utf8",
);

test("partner web chat waits for runtime readiness, not channel running state", () => {
  assert.match(chatSource, /data\.type === "ready"/);
  assert.match(chatSource, /disabled=\{!connected\}/);
  assert.doesNotMatch(chatSource, /if \(!running\)/);
  assert.doesNotMatch(chatSource, /disabled=\{!connected \|\| !running\}/);
});

test("partner tabs use a stable centered header column", () => {
  assert.match(
    pageSource,
    /grid-cols-\[minmax\(0,1fr\)_auto_minmax\(0,1fr\)\]/,
  );
  assert.match(pageSource, /<nav className="flex justify-self-center/);
});

test("partner chat has a complete archive and resume surface", () => {
  assert.match(pageSource, /handleArchiveConversation/);
  assert.match(pageSource, /archivePartnerSession\(partnerId, sessionKey\)/);
  assert.match(pageSource, /changeSessionKey\(freshPartnerSessionKey\(\)\)/);
  assert.match(archiveSource, /\.filter\(\s*\(session\) => session\.archived,/);
  assert.match(archiveSource, /resumePartnerSession/);
});
