import React, { useEffect } from "react";
import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import {
  SettingsProvider,
  useSettings,
} from "@/features/settings/store/SettingsStore";
import { THEME_STORAGE_KEY } from "@/lib/theme";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));

vi.mock("@/lib/api", () => ({
  apiUrl: (s: string) => s,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));
vi.mock("@/context/AppShellContext", () => ({
  useAppShell: () => ({
    codeBlockTheme: "github",
    codeBlockShowLineNumbers: false,
    codeBlockWrapLongLines: false,
  }),
}));
vi.mock("@/lib/llm-options", () => ({ invalidateLLMOptionsCache: vi.fn() }));

let settings: ReturnType<typeof useSettings>;

function reply(value: unknown, ok = true, status = ok ? 200 : 503) {
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Service Unavailable",
    json: async () => value,
  };
}

function installFetch(settingsOk: boolean, theme: string) {
  mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/api/settings" && method === "GET") {
      if (!settingsOk) return reply({ detail: "down" }, false);
      return reply({
        ui: {
          theme,
          language: "en",
          response_language: "en",
          code_block_theme: "github",
          code_block_show_line_numbers: false,
          code_block_wrap_long_lines: false,
        },
      });
    }
    if (url === "/api/system/status") return reply({ detail: "down" }, false);
    return reply({ draft: null });
  });
}

function Capture() {
  const value = useSettings();
  useEffect(() => {
    settings = value;
  }, [value]);
  return null;
}

async function ready() {
  render(
    <SettingsProvider>
      <Capture />
    </SettingsProvider>,
  );
  await waitFor(() => expect(settings.settingsLoading).toBe(false));
}

function uiPuts() {
  return mocks.fetch.mock.calls.filter(
    ([url, init]) =>
      url === "/api/settings/ui" &&
      (init as RequestInit | undefined)?.method === "PUT",
  );
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
});

it("shows a stored palette after settings fail to load, instead of the system placeholder", async () => {
  localStorage.setItem(THEME_STORAGE_KEY, "glass");
  installFetch(false, "system");

  await ready();

  expect(settings.settingsError).toBeTruthy();
  expect(settings.theme).toBe("glass");
});

it("does not apply the placeholder system theme when a later UI change is saved", async () => {
  localStorage.setItem(THEME_STORAGE_KEY, "glass");
  installFetch(false, "system");
  await ready();

  await act(async () => {
    await settings.updateLanguage("zh");
    await settings.updateTheme("dark");
  });
  await act(async () => {
    await settings.applyCatalog();
  });

  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("glass");
  expect(document.documentElement.classList.contains("theme-snow")).toBe(false);
  expect(document.documentElement.classList.contains("dark")).toBe(false);
  const puts = uiPuts();
  expect(puts).toHaveLength(1);
  const body = JSON.parse(String((puts[0][1] as RequestInit).body));
  expect(body.language).toBe("zh");
  expect(body).not.toHaveProperty("theme");
});

it("does not persist system when nothing is stored and settings fail to load", async () => {
  installFetch(false, "system");
  await ready();

  await act(async () => {
    await settings.updateLanguage("zh");
  });
  await act(async () => {
    await settings.applyCatalog();
  });

  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  const body = JSON.parse(String((uiPuts()[0][1] as RequestInit).body));
  expect(body).not.toHaveProperty("theme");
});

it("still sends the server theme after settings load", async () => {
  localStorage.setItem(THEME_STORAGE_KEY, "glass");
  installFetch(true, "dark");
  await ready();

  expect(settings.theme).toBe("dark");
  await act(async () => {
    await settings.updateLanguage("zh");
  });
  await act(async () => {
    await settings.applyCatalog();
  });

  const body = JSON.parse(String((uiPuts()[0][1] as RequestInit).body));
  expect(body.theme).toBe("dark");
  expect(body.language).toBe("zh");
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
});

it("includes the confirmed theme in a failed-load draft after retry", async () => {
  localStorage.setItem(THEME_STORAGE_KEY, "glass");
  document.documentElement.classList.add("dark", "theme-glass");
  installFetch(false, "system");
  await ready();

  await act(async () => {
    await settings.updateLanguage("zh");
    await settings.updateTheme("dark");
  });

  installFetch(true, "snow");
  await act(async () => {
    await settings.reloadSettings();
  });

  expect(settings.theme).toBe("snow");
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("glass");
  expect(document.documentElement.classList.contains("theme-glass")).toBe(true);

  await act(async () => {
    await settings.applyCatalog();
  });

  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("snow");
  expect(document.documentElement.classList.contains("theme-snow")).toBe(true);
  expect(document.documentElement.classList.contains("dark")).toBe(false);
  expect(document.documentElement.classList.contains("theme-glass")).toBe(false);
  const body = JSON.parse(String((uiPuts()[0][1] as RequestInit).body));
  expect(body.language).toBe("zh");
  expect(body.theme).toBe("snow");
});
