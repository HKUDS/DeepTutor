import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import type { RagProviderSummary } from "../lib/knowledge-api";
import {
  canConnectIma,
  createProviders,
  emptyImaLookupState,
  linkSourceEnabled,
  mergeImaKnowledgeBases,
  nextAutoName,
} from "../lib/ima-connection";

test("IMA belongs only to link-existing provider choices", () => {
  const providers = [
    { id: "ima", name: "IMA", description: "remote" },
    { id: "llamaindex", name: "LlamaIndex", description: "local" },
    { id: "pageindex", name: "PageIndex", description: "cloud" },
  ] as RagProviderSummary[];

  assert.deepEqual(
    createProviders(providers).map((provider) => provider.id),
    ["llamaindex", "pageindex"],
  );
  assert.equal(linkSourceEnabled(providers[0]), true);
  assert.equal(linkSourceEnabled({ ...providers[2], linkable: false }), false);
  assert.equal(linkSourceEnabled({ ...providers[1], linkable: true }), true);
});

test("leaving the IMA source clears credentials from the mounted flow", () => {
  const hookSource = readFileSync(
    path.resolve("hooks/useImaConnection.ts"),
    "utf8",
  );
  const modalSource = readFileSync(
    path.resolve("components/knowledge/CreateKbModal.tsx"),
    "utf8",
  );

  assert.match(hookSource, /setClientId\(""\);\s+setApiKey\(""\);/);
  assert.match(
    modalSource,
    /const handleClose = \(\) => {\s+imaConnection\.reset\(\);/,
  );
  assert.match(
    modalSource,
    /if \(source !== IMA_PROVIDER\) imaConnection\.reset\(\);/,
  );
});

test("automatic names never overwrite a manual DeepTutor name", () => {
  assert.equal(nextAutoName("", null, "IMA Notes"), "IMA Notes");
  assert.equal(nextAutoName("IMA Old", "IMA Old", "IMA New"), "IMA New");
  assert.equal(
    nextAutoName("My manual name", "IMA Old", "IMA New"),
    "My manual name",
  );
});

test("IMA pagination merges by id and keeps list order", () => {
  const merged = mergeImaKnowledgeBases(
    [
      { id: "kb-1", name: "Alpha", description: null },
      { id: "kb-2", name: "Beta", description: null },
    ],
    [
      { id: "kb-2", name: "Beta", description: "enriched" },
      { id: "kb-3", name: "Gamma", description: null },
    ],
  );

  assert.deepEqual(merged, [
    { id: "kb-1", name: "Alpha", description: null },
    { id: "kb-2", name: "Beta", description: "enriched" },
    { id: "kb-3", name: "Gamma", description: null },
  ]);
});

test("empty IMA lookup state removes selections and verification", () => {
  assert.deepEqual(emptyImaLookupState(), {
    status: "idle",
    knowledgeBases: [],
    selectedId: "",
    nextCursor: "",
    isEnd: true,
    manualVerification: null,
    lastAutoName: null,
  });
});

test("automatic IMA connection requires credentials and a selected id", () => {
  const base = {
    mode: "automatic" as const,
    name: "Notes",
    clientId: "cid",
    apiKey: "key",
    credentialsReady: true,
    selectedId: "kb-1",
    manualKnowledgeBaseId: "",
    manualVerification: null,
  };

  assert.equal(canConnectIma(base), true);
  assert.equal(canConnectIma({ ...base, credentialsReady: false }), false);
  assert.equal(canConnectIma({ ...base, selectedId: "" }), false);
});

test("the account credential pair connects without any typed credentials", () => {
  // Nothing is typed and nothing is sent — the server resolves the pair.
  assert.equal(
    canConnectIma({
      mode: "automatic",
      name: "Notes",
      clientId: "",
      apiKey: "",
      credentialsReady: true,
      selectedId: "kb-1",
      manualKnowledgeBaseId: "",
      manualVerification: null,
    }),
    true,
  );
});

test("manual IMA connection accepts only the current verified credential tuple", () => {
  const base = {
    mode: "manual" as const,
    name: "Notes",
    clientId: "cid",
    apiKey: "key",
    credentialsReady: true,
    selectedId: "",
    manualKnowledgeBaseId: "kb-1",
    manualVerification: {
      ok: true,
      clientId: "cid",
      apiKey: "key",
      knowledgeBaseId: "kb-1",
    },
  };

  assert.equal(canConnectIma(base), true);
  assert.equal(canConnectIma({ ...base, apiKey: "new-key" }), false);
  assert.equal(
    canConnectIma({ ...base, manualKnowledgeBaseId: "kb-2" }),
    false,
  );
  assert.equal(
    canConnectIma({
      ...base,
      manualVerification: { ...base.manualVerification, ok: false },
    }),
    false,
  );
});
