import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const source = readFileSync(
  path.resolve(process.cwd(), "components/partners/PartnerChat.tsx"),
  "utf8",
);

test("partner chat delegates streaming scroll control to useChatAutoScroll", () => {
  assert.match(
    source,
    /import \{ useChatAutoScroll \} from "@\/hooks\/useChatAutoScroll";/,
  );
  assert.match(source, /containerRef: scrollRef/);
  assert.match(source, /data-chat-scroll-root="true"/);
  assert.match(source, /onScroll=\{handleScroll\}/);
});

test("partner stream events do not imperatively fight user scrolling", () => {
  const streamStart = source.indexOf('data.type === "stream_event"');
  const doneStart = source.indexOf('data.type === "done"', streamStart);

  assert.notEqual(streamStart, -1, "stream_event handler should exist");
  assert.notEqual(doneStart, -1, "done handler should follow stream handlers");
  assert.doesNotMatch(
    source.slice(streamStart, doneStart),
    /scrollToBottom\s*\(/,
  );
});

test("sending a new partner turn re-arms live-follow mode", () => {
  const sendStart = source.indexOf("const handleSend = useCallback");
  const commandStart = source.indexOf("const command =", sendStart);

  assert.notEqual(sendStart, -1, "handleSend should exist");
  assert.notEqual(commandStart, -1, "command parsing should exist");
  assert.match(
    source.slice(sendStart, commandStart),
    /shouldAutoScrollRef\.current = true;/,
  );
});
