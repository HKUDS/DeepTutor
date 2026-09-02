import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  parseCapabilityCatalogPayload,
  sanitizeCapabilityConfig,
} from "../features/capabilities/model";
import {
  mergeCapabilityPresentations,
  visibleCapabilityPresentations,
} from "../features/capabilities/presentation";

test("backend descriptors own identity, availability, manifest, and schema", () => {
  const catalog = parseCapabilityCatalogPayload({
    capabilities: [
      "chat",
      {
        id: "extension_lab",
        kind: "plugin",
        available: false,
        manifest: { name: "Extension Lab", description: "Experimental tutor" },
        config_schema: {
          type: "object",
          properties: { depth: { type: "integer" } },
        },
      },
      { id: "extension_lab", available: true },
      { nope: true },
    ],
  });

  assert.equal(catalog.length, 2);
  assert.deepEqual(catalog[0], {
    id: "chat",
    kind: "capability",
    available: true,
    manifest: null,
    configSchema: null,
  });
  assert.equal(catalog[1].kind, "plugin");
  assert.equal(catalog[1].available, false);
  assert.equal(catalog[1].manifest?.name, "Extension Lab");
  assert.equal(catalog[1].configSchema?.properties?.depth.type, "integer");
});

test("unknown available extensions receive a generic presentation", () => {
  const merged = mergeCapabilityPresentations(
    parseCapabilityCatalogPayload({
      capabilities: [
        "chat",
        {
          id: "proof_coach",
          available: true,
          manifest: { description: "Checks a proof step by step" },
        },
        { id: "offline_plugin", available: false },
      ],
    }),
  );
  assert.equal(merged[0].value, "");
  assert.equal(merged[1].value, "proof_coach");
  assert.equal(merged[1].label, "Proof Coach");
  assert.equal(merged[1].description, "Checks a proof step by step");
  assert.equal(
    merged.some((item) => item.value === "offline_plugin"),
    false,
  );
});

test("direct mastery capability is catalogued but not duplicated as a browser action", () => {
  const merged = mergeCapabilityPresentations(
    parseCapabilityCatalogPayload({ capabilities: ["chat", "mastery_path"] }),
  );

  assert.equal(
    merged.some((item) => item.value === "mastery_path"),
    true,
  );
  assert.equal(
    visibleCapabilityPresentations(merged).some(
      (item) => item.value === "mastery_path",
    ),
    false,
  );
});

test("catalog merging returns isolated turn presentation objects", () => {
  const descriptors = parseCapabilityCatalogPayload({ capabilities: ["chat"] });
  const first = mergeCapabilityPresentations(descriptors);
  const second = mergeCapabilityPresentations(descriptors);
  const secondLength = second[0].allowedTools.length;
  first[0].allowedTools.length = 0;
  assert.equal(second[0].allowedTools.length, secondLength);
});

test("safe schema fields are normalized and unknown fields are rejected", () => {
  const schema = {
    type: "object",
    required: ["mode"],
    additionalProperties: false,
    properties: {
      mode: { type: "string", enum: ["fast", "deep"] },
      depth: { type: "integer", minimum: 1, maximum: 5 },
      citations: { type: "boolean" },
    },
  } as const;
  assert.deepEqual(
    sanitizeCapabilityConfig(schema, {
      mode: "deep",
      depth: 3,
      citations: true,
    }),
    { ok: true, value: { mode: "deep", depth: 3, citations: true } },
  );
  const invalid = sanitizeCapabilityConfig(schema, {
    mode: "unsafe",
    depth: 9,
    injected: "secret",
  });
  assert.equal(invalid.ok, false);
  if (!invalid.ok) assert.equal(invalid.errors.length, 3);
});

test("component-owned capability types cannot return", () => {
  const composer = fs.readFileSync(
    path.resolve(process.cwd(), "components/chat/home/ChatComposer.tsx"),
    "utf8",
  );
  assert.doesNotMatch(composer, /export interface CapabilityDef/);
  assert.equal(
    fs.existsSync(path.resolve(process.cwd(), "lib/chat-capabilities.ts")),
    false,
  );
});
