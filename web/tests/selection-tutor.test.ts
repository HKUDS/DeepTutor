import test from "node:test";
import assert from "node:assert/strict";
import {
  buildSelectionTutorConfig,
  normalizeSelectedText,
  selectionTutorKey,
} from "../lib/selection-tutor";

test("normalizes selected chat text without flattening paragraphs", () => {
  assert.equal(
    normalizeSelectedText("  first   line\r\n\r\n\r\n second\tline  "),
    "first line\n\nsecond line",
  );
});

test("selection tutor keys are stable per passage and parent session", () => {
  const a = selectionTutorKey("rc", "session-a", 42);
  assert.equal(a, selectionTutorKey("rc", "session-a", 42));
  assert.notEqual(a, selectionTutorKey("rc", "session-b", 42));
  assert.notEqual(a, selectionTutorKey("rc", "session-a", 43));
  assert.notEqual(a, selectionTutorKey("wait() blocks", "session-a", 42));
});

test("builds selected text context with its containing message", () => {
  assert.deepEqual(
    buildSelectionTutorConfig({
      selectedText: "  rc ",
      parentSessionId: "parent-1",
      sourceMessageId: 42,
      sourceMessageText:
        "int rc = fork();\n父进程中的 rc 是子进程 PID，子进程中的 rc 是 0。",
      sourceMessageRole: "assistant",
    }),
    {
      selection_tutor_context: {
        selected_text: "rc",
        parent_session_id: "parent-1",
        source_message_id: 42,
        source_message_text:
          "int rc = fork();\n父进程中的 rc 是子进程 PID，子进程中的 rc 是 0。",
        source_message_role: "assistant",
      },
    },
  );
});
