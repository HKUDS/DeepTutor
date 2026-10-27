import assert from "node:assert/strict";
import test from "node:test";

import type { StreamEvent } from "../features/chat/model/protocol";
import { lectureRevisionOnMessage } from "../lib/lecture-preview";

function toolResult(metadata: Record<string, unknown>): StreamEvent {
  return {
    type: "tool_result",
    source: "chat",
    stage: "responding",
    content: "",
    metadata: { tool_metadata: metadata },
    session_id: "session-1",
    turn_id: "turn-1",
    seq: 1,
    timestamp: 0,
  };
}
