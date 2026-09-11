import test from "node:test";
import assert from "node:assert/strict";

import { knowledgeEngineGroup } from "../lib/knowledge-engine-group";

test("knowledge engines: built-in providers stay in their expected deployment group", () => {
  for (const id of ["llamaindex", "pageindex-oss", "graphrag", "lightrag"]) {
    assert.equal(knowledgeEngineGroup({ id }), "local", id);
  }

  assert.equal(knowledgeEngineGroup({ id: "lightrag-server" }), "server");

  for (const id of ["pageindex", "ima"]) {
    assert.equal(knowledgeEngineGroup({ id }), "cloud", id);
  }
});

test("knowledge engines: unknown providers fall back to their credential requirement", () => {
  assert.equal(
    knowledgeEngineGroup({ id: "future-hosted", requires_api_key: true }),
    "cloud",
  );
  assert.equal(knowledgeEngineGroup({ id: "future-local" }), "local");
});
