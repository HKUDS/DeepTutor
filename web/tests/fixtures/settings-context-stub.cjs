"use strict";

// Test-only stub for the SettingsContext module.
//
// The node test runner compiles tests/*.ts to dist/node-tests and executes them
// without a browser, Next router, or a running backend. Rendering
// ServiceConfigEditor through the real SettingsProvider is therefore not
// possible here: SettingsProvider fetches the catalog in a mount effect (which
// server-side renderToStaticMarkup never runs) and depends on next/navigation.
//
// This stub lets a focused test render the editor against a controlled catalog
// by providing the handful of runtime values ServiceConfigEditor (and its
// direct children) consume from the module, reading the mock value from a
// global installed by the test. The render tree under test is the real JSX;
// only the data source is injected.

const EXPLICIT_LLM_API_PROTOCOL_VALUES = [
  "openai_chat_completions",
  "openai_responses",
  "anthropic_messages",
];

function getActiveProfile(catalog, serviceName) {
  const service = catalog && catalog.services && catalog.services[serviceName];
  if (!service) return null;
  return (
    service.profiles.find((p) => p.id === service.active_profile_id) ||
    service.profiles[0] ||
    null
  );
}

function getActiveModel(catalog, serviceName) {
  if (serviceName === "search") return null;
  const service = catalog && catalog.services && catalog.services[serviceName];
  const profile = getActiveProfile(catalog, serviceName);
  if (!service || !profile) return null;
  return (
    profile.models.find((m) => m.id === service.active_model_id) ||
    profile.models[0] ||
    null
  );
}

function useSettings() {
  const value = global.__SETTINGS_EDITOR_MOCK__;
  if (!value) {
    throw new Error(
      "settings-editor test did not install global.__SETTINGS_EDITOR_MOCK__",
    );
  }
  return value;
}

module.exports = {
  EXPLICIT_LLM_API_PROTOCOL_VALUES,
  getActiveProfile,
  getActiveModel,
  useSettings,
};
