import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { useTranslation } from "react-i18next";

import { AppShellProvider } from "../context/AppShellContext";
import { I18nClientBridge } from "../i18n/I18nClientBridge";
import { loadInitialLanguage } from "../lib/server-ui-settings";

test("server bootstrap loads the persisted language before rendering", async () => {
  let capturedInput: RequestInfo | URL | undefined;
  let capturedInit: RequestInit | undefined;

  const language = await loadInitialLanguage(async (input, init) => {
    capturedInput = input;
    capturedInit = init;
    return {
      ok: true,
      json: async () => ({ language: "zh" }),
    } as Response;
  }, "http://backend.test:8001");

  assert.equal(
    capturedInput?.toString(),
    "http://backend.test:8001/api/v1/settings/ui",
  );
  assert.equal(capturedInit?.cache, "no-store");
  assert.equal(language, "zh");
});

test("server bootstrap ignores failed or malformed language responses", async () => {
  assert.equal(
    await loadInitialLanguage(
      async () => ({ ok: false, json: async () => ({}) }) as Response,
      "http://backend.test:8001",
    ),
    null,
  );
  assert.equal(
    await loadInitialLanguage(
      async () =>
        ({ ok: true, json: async () => ({ language: "fr" }) }) as Response,
      "http://backend.test:8001",
    ),
    null,
  );
});

test("app shell server-renders translations with the injected language", () => {
  function TranslationProbe() {
    const { t } = useTranslation();
    return React.createElement("span", null, t("Home"));
  }

  const html = renderToStaticMarkup(
    React.createElement(
      AppShellProvider,
      { initialLanguage: "zh" },
      React.createElement(
        I18nClientBridge,
        null,
        React.createElement(TranslationProbe),
      ),
    ),
  );

  assert.equal(html, "<span>主页</span>");
});
