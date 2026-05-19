import test from "node:test";
import assert from "node:assert/strict";

import { extractRetrievalSummary } from "../lib/retrieval-summary";

test("extractRetrievalSummary groups rag tool traces by knowledge base", () => {
  const summary = extractRetrievalSummary({
    tool_traces: [
      {
        name: "rag",
        arguments: { kb_name: "linear-algebra" },
        sources: [{ kb_name: "linear-algebra" }],
        metadata: {
          sources: [
            {
              title: "svd.pdf",
              chunk_id: "c1",
            },
            {
              title: "svd.pdf",
              chunk_id: "c2",
            },
            {
              title: "eigenvalues.md",
              chunk_id: "c3",
            },
          ],
        },
      },
      {
        name: "rag",
        arguments: { kb_name: "probability" },
        sources: [{ kb_name: "probability" }],
        metadata: {
          sources: [
            {
              source: "/data/user/knowledge/probability/bayes.txt",
              chunk_id: "p1",
            },
          ],
        },
      },
      {
        name: "web_search",
        metadata: {},
      },
    ],
  });

  assert.ok(summary);
  assert.equal(summary?.totalChunks, 4);
  assert.equal(summary?.totalFiles, 3);
  assert.deepEqual(summary?.knowledgeBases, [
    {
      kbName: "linear-algebra",
      files: ["svd.pdf", "eigenvalues.md"],
      chunkCount: 3,
    },
    {
      kbName: "probability",
      files: ["bayes.txt"],
      chunkCount: 1,
    },
  ]);
});

test("extractRetrievalSummary returns null when no rag traces are present", () => {
  assert.equal(
    extractRetrievalSummary({
      tool_traces: [{ name: "web_search", metadata: {} }],
    }),
    null,
  );
});
