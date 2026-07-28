import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const hookSource = readFileSync(
  path.resolve(process.cwd(), "hooks/useChatAutoScroll.ts"),
  "utf8",
);
const chatSource = readFileSync(
  path.resolve(
    process.cwd(),
    "app/(workspace)/home/[[...sessionId]]/page.tsx",
  ),
  "utf8",
);
const partnerSource = readFileSync(
  path.resolve(process.cwd(), "components/partners/PartnerChat.tsx"),
  "utf8",
);

test("switching chat sessions stores and restores the transcript position", () => {
  assert.match(hookSource, /scrollPositionsRef = useRef\(new Map<string, number>\(\)\)/);
  assert.match(
    hookSource,
    /saveScrollPosition\(\);[\s\S]*pendingRestoreRef\.current =[\s\S]*position !== undefined/,
  );
  assert.match(hookSource, /container\.scrollTop = pending\.position;/);
});

test("main and partner chats identify their active transcript", () => {
  assert.match(chatSource, /scrollKey: state\.sessionId/);
  assert.match(
    partnerSource,
    /scrollKey: `\$\{partnerId\}:\$\{sessionKey \?\? ""\}`/,
  );
});
