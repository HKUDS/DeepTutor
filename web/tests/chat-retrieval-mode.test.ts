import test from "node:test";
import assert from "node:assert/strict";

import { applyChatRetrievalMode } from "../lib/chat-retrieval-mode";

test("applyChatRetrievalMode keeps current selection in auto mode", () => {
  assert.deepEqual(
    applyChatRetrievalMode(
      ["brainstorm", "web_search", "reason"],
      ["math", "physics"],
      "auto",
    ),
    {
      enabledTools: ["brainstorm", "web_search", "reason"],
      knowledgeBases: ["math", "physics"],
    },
  );
});

test("applyChatRetrievalMode removes web search in kb_only mode", () => {
  assert.deepEqual(
    applyChatRetrievalMode(["web_search", "code_execution"], ["math"], "kb_only"),
    {
      enabledTools: ["code_execution"],
      knowledgeBases: ["math"],
    },
  );
});

test("applyChatRetrievalMode forces web search in kb_web mode", () => {
  assert.deepEqual(
    applyChatRetrievalMode(["code_execution"], ["math"], "kb_web"),
    {
      enabledTools: ["code_execution", "web_search"],
      knowledgeBases: ["math"],
    },
  );
});

test("applyChatRetrievalMode disables both kb and web retrieval in off mode", () => {
  assert.deepEqual(
    applyChatRetrievalMode(["web_search", "reason"], ["math"], "off"),
    {
      enabledTools: ["reason"],
      knowledgeBases: [],
    },
  );
});
