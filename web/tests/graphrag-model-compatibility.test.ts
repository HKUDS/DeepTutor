import test from "node:test";
import assert from "node:assert/strict";

import { testGraphRagModelCompatibility } from "../lib/knowledge-api";
import { canApplyGraphRagModelCandidate } from "../lib/graphrag-model-compatibility";

test("GraphRAG candidate probe sends catalog IDs without activating the model", async () => {
  const originalFetch = globalThis.fetch;
  let requestUrl = "";
  let requestInit: RequestInit | undefined;
  globalThis.fetch = async (input, init) => {
    requestUrl = String(input);
    requestInit = init;
    return new Response(
      JSON.stringify({
        status: "compatible",
        compatible: true,
        code: "graphrag_model_compatible",
        message: "The model returned valid GraphRAG structured output.",
        model: "gpt-4o-mini",
        binding: "openai",
        retryable: false,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const result = await testGraphRagModelCompatibility("profile-a", "model-b");

    assert.equal(
      requestUrl,
      "/api/v1/knowledge/rag-pipelines/graphrag/model-compatibility",
    );
    assert.equal(requestInit?.method, "POST");
    assert.deepEqual(JSON.parse(String(requestInit?.body)), {
      profile_id: "profile-a",
      model_id: "model-b",
    });
    assert.equal(result.status, "compatible");
    assert.equal(result.compatible, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("only the exact candidate that passed compatibility can be applied", () => {
  const compatible = {
    status: "compatible" as const,
    compatible: true,
    code: "graphrag_model_compatible",
    message: "ok",
    model: "gpt-4o-mini",
    binding: "openai",
    retryable: false,
  };

  assert.equal(
    canApplyGraphRagModelCandidate({
      activeKey: "profile-a::model-a",
      candidateKey: "profile-a::model-b",
      testedKey: "profile-a::model-b",
      result: compatible,
    }),
    true,
  );
  assert.equal(
    canApplyGraphRagModelCandidate({
      activeKey: "profile-a::model-a",
      candidateKey: "profile-a::model-c",
      testedKey: "profile-a::model-b",
      result: compatible,
    }),
    false,
    "changing the dropdown must invalidate the previous probe",
  );
  assert.equal(
    canApplyGraphRagModelCandidate({
      activeKey: "profile-a::model-b",
      candidateKey: "profile-a::model-b",
      testedKey: "profile-a::model-b",
      result: compatible,
    }),
    false,
    "the already-active model does not need to be applied again",
  );
});
