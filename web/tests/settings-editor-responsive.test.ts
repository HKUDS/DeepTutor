import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import Module from "node:module";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// ─── Window mock ────────────────────────────────────────────────────────────
// Some imported modules read window.* lazily; mirror the mock the other node
// tests install so those reads are harmless under the plain node runner.
let mockLocalStorage: Record<string, string> = {};
let mockSessionStorage: Record<string, string> = {};

function mockWindow() {
  global.window = {
    localStorage: {
      getItem: (key: string) => mockLocalStorage[key] ?? null,
      setItem: (key: string, value: string) => {
        mockLocalStorage[key] = value;
      },
      removeItem: (key: string) => {
        delete mockLocalStorage[key];
      },
    },
    sessionStorage: {
      getItem: (key: string) => mockSessionStorage[key] ?? null,
      setItem: (key: string, value: string) => {
        mockSessionStorage[key] = value;
      },
      removeItem: (key: string) => {
        delete mockSessionStorage[key];
      },
    },
    dispatchEvent: () => true,
    matchMedia: () => ({
      matches: false,
      media: "",
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => true,
    }),
  } as any;
  global.localStorage = mockLocalStorage as any;
  global.sessionStorage = mockSessionStorage as any;
}

mockWindow();

// ─── SettingsContext stub hook ──────────────────────────────────────────────
// The real SettingsProvider fetches its catalog in a mount effect and depends
// on next/navigation, so it cannot be rendered by the node test runner. These
// tests render the real ServiceConfigEditor JSX against a controlled catalog by
// swapping the module that provides useSettings/getActiveProfile/getActiveModel
// (see tests/fixtures/settings-context-stub.cjs). Install the hook before any
// component module is required.
const settingsStubPath = path.join(
  process.cwd(),
  "tests",
  "fixtures",
  "settings-context-stub.cjs",
);

const moduleInternals = Module as unknown as {
  _resolveFilename: (
    request: string,
    parent: NodeModule | null | undefined,
    isMain: boolean,
    options?: unknown,
  ) => string;
};

const originalResolveFilename = moduleInternals._resolveFilename;
moduleInternals._resolveFilename = function (
  request: string,
  parent: NodeModule | null | undefined,
  isMain: boolean,
  options?: unknown,
) {
  const resolved = originalResolveFilename.call(
    this,
    request,
    parent,
    isMain,
    options,
  );
  if (resolved && resolved.endsWith("components/settings/SettingsContext.js")) {
    return settingsStubPath;
  }
  return resolved;
};

// ─── Fixtures ───────────────────────────────────────────────────────────────

type ServiceName =
  | "llm"
  | "embedding"
  | "search"
  | "tts"
  | "stt"
  | "imagegen"
  | "videogen";

const FOUR_LLM_PROFILES = [
  {
    id: "llm-profile-1",
    name: "Primary Chat Model Profile",
    binding: "openai",
    base_url: "",
    api_key: "",
    api_key_set: false,
    api_version: "",
    api_protocol: "openai_chat_completions",
    strict_protocol: false,
    models: [
      {
        id: "llm-model-1",
        name: "chat-model-alpha",
        model: "gpt-4o",
        context_window: "128000",
      },
    ],
  },
  {
    id: "llm-profile-2",
    name: "Secondary Reasoning Profile",
    binding: "anthropic",
    base_url: "",
    api_key: "",
    api_key_set: false,
    api_version: "",
    api_protocol: "anthropic_messages",
    strict_protocol: false,
    models: [
      {
        id: "llm-model-2",
        name: "chat-model-beta",
        model: "claude-opus-5",
        context_window: "200000",
      },
    ],
  },
  {
    id: "llm-profile-3",
    name: "Local Fast Model Profile",
    binding: "deepseek",
    base_url: "",
    api_key: "",
    api_key_set: false,
    api_version: "",
    api_protocol: "openai_chat_completions",
    strict_protocol: false,
    models: [
      {
        id: "llm-model-3",
        name: "chat-model-gamma",
        model: "deepseek-v3",
        context_window: "64000",
      },
    ],
  },
  {
    id: "llm-profile-4",
    name: "Long Context Archive Profile",
    binding: "moonshot",
    base_url: "",
    api_key: "",
    api_key_set: false,
    api_version: "",
    api_protocol: "openai_responses",
    strict_protocol: true,
    models: [
      {
        id: "llm-model-4",
        name: "chat-model-delta",
        model: "kimi-k2",
        context_window: "256000",
      },
    ],
  },
];

function makeMockSettings(service: ServiceName, profiles: any[]) {
  const draft: any = {
    version: 1,
    services: {
      llm: { active_profile_id: null, active_model_id: null, profiles: [] },
      embedding: {
        active_profile_id: null,
        active_model_id: null,
        profiles: [],
      },
      search: { active_profile_id: null, profiles: [] },
      tts: { active_profile_id: null, active_model_id: null, profiles: [] },
      stt: { active_profile_id: null, active_model_id: null, profiles: [] },
      imagegen: {
        active_profile_id: null,
        active_model_id: null,
        profiles: [],
      },
      videogen: {
        active_profile_id: null,
        active_model_id: null,
        profiles: [],
      },
    },
  };
  const svc = draft.services[service];
  svc.profiles = profiles;
  svc.active_profile_id = profiles[0]?.id ?? null;
  if (service !== "search") {
    svc.active_model_id = profiles[0]?.models?.[0]?.id ?? null;
  }

  return {
    draft,
    catalogEditable: true,
    settingsError: null,
    providers: {
      llm: [
        { value: "openai", label: "OpenAI", base_url: "" },
        { value: "anthropic", label: "Anthropic", base_url: "" },
        { value: "deepseek", label: "DeepSeek", base_url: "" },
        { value: "moonshot", label: "Moonshot", base_url: "" },
      ],
      embedding: [
        { value: "openai", label: "OpenAI", base_url: "", default_dim: "3072" },
      ],
      search: [],
      tts: [],
      stt: [],
      imagegen: [
        {
          value: "openai",
          label: "OpenAI",
          base_url: "",
          default_model: "gpt-image-2",
        },
      ],
      videogen: [],
    },
    protocolOptions: [],
    language: "en" as const,
    embeddingCapabilities: null,
    logs: "",
    testRunning: null,
    mutateCatalog: () => {},
    addProfile: () => {},
    removeActiveProfile: () => {},
    addModel: () => {},
    removeActiveModel: () => {},
    updateProfileField: () => {},
    updateProfileBoolField: () => {},
    updateProfileApiKey: () => {},
    updateModelField: () => {},
    updateModelBoolField: () => {},
    updateContextWindowField: () => {},
    llmContextDetection: null,
    applyDetectedContextWindow: () => {},
    runDetailedTest: async () => {},
    embeddingDefaultDim: () => "3072",
  } as any;
}

async function renderEditor(service: ServiceName, profiles: any[]) {
  (global as any).__SETTINGS_EDITOR_MOCK__ = makeMockSettings(service, profiles);
  const { ServiceConfigEditor } = await import(
    "../components/settings/ServiceConfigEditor"
  );
  return renderToStaticMarkup(
    React.createElement(ServiceConfigEditor, { service }),
  );
}

const serviceEditorSourcePath = path.join(
  process.cwd(),
  "components",
  "settings",
  "ServiceConfigEditor.tsx",
);
function readServiceEditorSource() {
  return fs.readFileSync(serviceEditorSourcePath, "utf8");
}

// ─── Rendered behavior checks (deterministic, no backend) ──────────────────

test("settings-editor-responsive: LLM editor renders all four profiles with full-name title affordance", async () => {
  const html = await renderEditor("llm", FOUR_LLM_PROFILES);

  for (const profile of FOUR_LLM_PROFILES) {
    assert.ok(
      html.includes(profile.name),
      `expected profile name in rendered editor: ${profile.name}`,
    );
  }

  // Truncation stays (visual), but every profile row carries the full name in
  // the native title tooltip, not just the "Double-click to rename" hint.
  assert.ok(
    html.includes(
      `title="${FOUR_LLM_PROFILES[0].name} — Double-click to rename"`,
    ),
    "profile row title should expose the full profile name",
  );
  assert.ok(
    html.includes(
      `title="${FOUR_LLM_PROFILES[3].name} — Double-click to rename"`,
    ),
    "the fourth (deepest) profile row should also expose its full name",
  );
  // The truncated visual label is preserved in the DOM text node.
  assert.match(html, /<span[^>]*class="[^"]*truncate[^"]*"/);
});

test("settings-editor-responsive: embedding editor renders the profile list above the editor on narrow screens", async () => {
  const embedProfiles = [
    {
      id: "embedding-profile-1",
      name: "Embedding Profile",
      binding: "openai",
      base_url: "",
      api_key: "",
      api_key_set: false,
      api_version: "",
      models: [
        {
          id: "embedding-model-1",
          name: "text-embedding-3-large",
          model: "text-embedding-3-large",
          dimension: "3072",
          send_dimensions: true,
        },
      ],
    },
  ];
  const html = await renderEditor("embedding", embedProfiles);

  // Mobile-first: single column (profile list stacked above the editor).
  assert.match(
    html,
    /class="grid grid-cols-1 items-start gap-5 md:grid-cols-\[200px_minmax\(0,1fr\)\]"/,
    "editor grid must stack at narrow widths and switch to two columns at md",
  );
  // The profile list must not pin itself to the viewport on mobile (it would
  // cover the editor below); sticky only applies from md up.
  assert.match(
    html,
    /<aside[^>]*class="[^"]*md:sticky md:top-4[^"]*"/,
    "profile list sticky should be gated behind the md breakpoint",
  );
  const asideMatch = html.match(/<aside[^>]*class="([^"]*)"/);
  assert.ok(asideMatch, "profile list aside should render");
  assert.doesNotMatch(
    asideMatch[1],
    /(^|[\s])sticky(?=[\s"])/,
    "the aside must not carry a bare sticky class for the mobile layout",
  );
});

test("settings-editor-responsive: image generation identifies openai_images as a read-only protocol", async () => {
  const imageProfiles = [
    {
      id: "imagegen-profile-1",
      name: "Image Generation Profile",
      binding: "openai",
      base_url: "",
      api_key: "",
      api_key_set: false,
      api_version: "",
      models: [
        {
          id: "imagegen-model-1",
          name: "imagegen-gpt-image-2",
          model: "gpt-image-2",
          size: "1024x1024",
        },
      ],
    },
  ];
  const html = await renderEditor("imagegen", imageProfiles);

  // The protocol identity is visible and the active image model is unchanged.
  assert.ok(html.includes("openai_images"), "image protocol identity must render");
  assert.match(
    html,
    /<code[^>]*>openai_images<\/code>/,
    "openai_images must be rendered as a read-only code badge, not a select option",
  );
  assert.ok(
    html.includes("gpt-image-2"),
    "active image model should remain gpt-image-2",
  );
  assert.ok(
    html.includes("imagegen-gpt-image-2"),
    "active image profile/model label should remain imagegen-gpt-image-2",
  );
});

// ─── Source-level regression coverage ───────────────────────────────────────
// These guard the concrete classes/attributes that implement the responsive
// and accessibility behavior. A rendered behavior check is preferred and is
// covered above; these source checks lock the invariants the rendered check
// depends on (mobile-first grid, sticky gating, read-only protocol badge).

test("settings-editor-responsive: editor grid is mobile-first two-column at md", () => {
  const source = readServiceEditorSource();
  assert.match(
    source,
    /grid grid-cols-1 items-start gap-5 md:grid-cols-\[200px_minmax\(0,1fr\)\]/,
    "main editor grid should stack on mobile and become two-column at md",
  );
  assert.match(
    source,
    /<aside className="self-start[^"]*md:sticky md:top-4"/,
    "profile list sticky should be gated behind md so mobile scrolling is not blocked",
  );
  assert.doesNotMatch(
    source,
    /<aside className="sticky top-4/,
    "the fixed single-breakpoint sticky aside must be gone",
  );
});

test("settings-editor-responsive: every profile row exposes its full name via a native title", () => {
  const source = readServiceEditorSource();
  assert.match(
    source,
    /\$\{profile\.name\} — \$\{t\("Double-click to rename"\)\}/,
    "profile row title should prepend the full profile name to the rename hint",
  );
  assert.match(
    source,
    /isManagedProfile\s*\?\s*profile\.name/,
    "managed (read-only) profiles must still expose their full name as the title",
  );
  assert.match(
    source,
    /className=\{`min-w-0 flex-1 truncate text-\[13px\] leading-tight/,
    "the visual profile label should stay truncated (CSS-only) so the DOM keeps the full name",
  );
});

test("settings-editor-responsive: model chips expose the full model label too", () => {
  const source = readServiceEditorSource();
  assert.match(
    source,
    /aria-label=\{label\}/,
    "model chips should carry an explicit accessible label with the full name",
  );
  assert.match(
    source,
    /\$\{label\} — \$\{t\("Double-click to rename"\)\}/,
    "model chip title should include the full model label before the rename hint",
  );
});

test("settings-editor-responsive: image protocol identity is read-only and LLM protocol selection is unchanged", () => {
  const source = readServiceEditorSource();
  assert.match(
    source,
    /service === "imagegen" &&/,
    "image protocol identity should only render for the imagegen service",
  );
  assert.match(
    source,
    /\{"openai_images"\}/,
    "image protocol identity should render the openai_images value",
  );
  assert.match(
    source,
    /data-protocol-identity="imagegen"/,
    "image protocol identity block should be targetable for the regression",
  );
  assert.match(
    source,
    /t\("API Protocol"\)/,
    "image protocol identity should reuse the existing API Protocol label",
  );

  // The imagegen protocol block must not contain a <select> (unsupported
  // protocols are not presented as editable choices).
  const blockStart = source.indexOf('data-protocol-identity="imagegen"');
  assert.ok(blockStart >= 0, "image protocol identity block should exist");
  const blockTail = source.slice(blockStart, blockStart + 900);
  assert.doesNotMatch(
    blockTail,
    /<select/,
    "image protocol identity must be read-only — no protocol select",
  );
  assert.doesNotMatch(
    blockTail,
    /EXPLICIT_LLM_API_PROTOCOL_VALUES/,
    "image protocol identity must not reuse the LLM protocol option list",
  );

  // LLM protocol selection is untouched: still derived from the explicit
  // list and the legacy auto state stays a disabled compatibility option.
  assert.match(
    source,
    /EXPLICIT_LLM_API_PROTOCOL_VALUES/,
    "LLM protocol selection should keep deriving from the explicit protocol list",
  );
  assert.match(
    source,
    /value="auto"\s*\n?\s*disabled/,
    "legacy auto compatibility state should remain disabled",
  );
});

test("settings-editor-responsive: new image protocol helper string has en/zh locale parity", () => {
  const key =
    "Image requests for this profile use the OpenAI Images API protocol. This value is fixed by DeepTutor.";
  const enApp = fs.readFileSync(
    path.join(process.cwd(), "locales", "en", "app.json"),
    "utf8",
  );
  const zhApp = fs.readFileSync(
    path.join(process.cwd(), "locales", "zh", "app.json"),
    "utf8",
  );
  assert.ok(enApp.includes(`"${key}"`), "en locale should carry the new key");
  assert.ok(zhApp.includes(`"${key}"`), "zh locale should carry the new key");
});
