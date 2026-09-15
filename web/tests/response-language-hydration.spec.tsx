import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { AppShellProvider, useAppShell } from "@/context/AppShellContext";
import {
  LANGUAGE_STORAGE_KEY,
  RESPONSE_LANGUAGE_STORAGE_KEY,
  readStoredResponseLanguage,
  writeStoredResponseLanguage,
} from "@/context/app-shell-storage";
import { apiFetch } from "@/lib/api";
import { buildStartTurnInput } from "@/features/chat/controllers/buildStartTurnInput";
import { SettingsProvider } from "@/features/settings/store/SettingsStore";
import {
  UiSettingsProvider,
  useUiSettings,
} from "@/features/settings/store/UiSettingsProvider";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  apiUrl: (path: string) => path,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (text: string) => text }),
}));

function LanguageProbe() {
  const { language, languageReady } = useAppShell();
  return (
    <output aria-label="language" data-ready={languageReady}>
      {language}
    </output>
  );
}

function SettingsProbe() {
  const { responseLanguage } = useUiSettings();
  return <output aria-label="response language">{responseLanguage}</output>;
}

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

it.each([
  ["en", "zh", undefined],
  ["en", "zh", "en"],
  ["zh", "en", "zh"],
] as const)(
  "keeps UI %s while refreshing output to %s from cache %s",
  async (ui, response, cachedResponse) => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, ui);
    if (cachedResponse) {
      localStorage.setItem(RESPONSE_LANGUAGE_STORAGE_KEY, cachedResponse);
    }
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      json: async () => ({ language: response, response_language: response }),
    } as Response);

    render(
      <AppShellProvider><LanguageProbe /></AppShellProvider>,
    );

    await waitFor(() => expect(readStoredResponseLanguage()).toBe(response));
    expect(screen.getByLabelText("language")).toHaveTextContent(ui);
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe(ui);
    expect(apiFetch).toHaveBeenCalledWith("/api/settings/ui", expect.anything());
    for (const sessionId of [null, "existing-session"]) {
      expect(
        buildStartTurnInput({
          content: "Continue",
          sessionId,
          language: readStoredResponseLanguage(),
        }).language,
      ).toBe(response);
    }
  },
);

it("inherits the server UI language only for a legacy response preference", async () => {
  localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
  vi.mocked(apiFetch).mockResolvedValue({
    ok: true,
    json: async () => ({ language: "zh" }),
  } as Response);

  render(<AppShellProvider><LanguageProbe /></AppShellProvider>);

  await waitFor(() => expect(readStoredResponseLanguage()).toBe("zh"));
  expect(screen.getByLabelText("language")).toHaveTextContent("en");
});

it("does not overwrite a choice made while the settings request is pending", async () => {
  let resolve!: (response: Response) => void;
  vi.mocked(apiFetch).mockImplementation(
    () => new Promise<Response>((done) => { resolve = done; }),
  );
  render(<AppShellProvider><LanguageProbe /></AppShellProvider>);

  await act(async () => {
    writeStoredResponseLanguage("en");
    resolve({
      ok: true,
      json: async () => ({ language: "zh", response_language: "zh" }),
    } as Response);
  });

  expect(readStoredResponseLanguage()).toBe("en");
});

it("keeps cached choices when settings cannot be loaded", async () => {
  localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
  localStorage.setItem(RESPONSE_LANGUAGE_STORAGE_KEY, "zh");
  vi.mocked(apiFetch).mockRejectedValue(new Error("offline"));

  render(<AppShellProvider><LanguageProbe /></AppShellProvider>);

  await waitFor(() =>
    expect(screen.getByLabelText("language")).toHaveAttribute("data-ready", "true"),
  );
  expect(readStoredResponseLanguage()).toBe("zh");
});

it("settings hydration updates the chat cache as well as the displayed choice", async () => {
  localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
  localStorage.setItem(RESPONSE_LANGUAGE_STORAGE_KEY, "en");
  vi.mocked(apiFetch).mockImplementation(async (url) => {
    if (url === "/api/settings") {
      return {
        ok: true,
        json: async () => ({
          ui: { language: "en", response_language: "zh", theme: "snow" },
        }),
      } as Response;
    }
    // The settings page must repair the cache even if app-shell bootstrap fails.
    return { ok: false } as Response;
  });

  render(
    <AppShellProvider>
      <SettingsProvider>
        <UiSettingsProvider><SettingsProbe /></UiSettingsProvider>
      </SettingsProvider>
    </AppShellProvider>,
  );

  await waitFor(() =>
    expect(screen.getByLabelText("response language")).toHaveTextContent("zh"),
  );
  expect(readStoredResponseLanguage()).toBe("zh");
  expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
});

it("hydrates separate interface and output choices in a fresh browser", async () => {
  vi.mocked(apiFetch).mockResolvedValue({
    ok: true,
    json: async () => ({ language: "en", response_language: "zh" }),
  } as Response);

  render(<AppShellProvider><LanguageProbe /></AppShellProvider>);

  await waitFor(() => expect(readStoredResponseLanguage()).toBe("zh"));
  expect(screen.getByLabelText("language")).toHaveTextContent("en");
});

it("does not write preferences after the provider unmounts", async () => {
  let resolve!: (response: Response) => void;
  vi.mocked(apiFetch).mockImplementation(
    () => new Promise<Response>((done) => { resolve = done; }),
  );
  const { unmount } = render(<AppShellProvider><LanguageProbe /></AppShellProvider>);
  unmount();

  await act(async () => {
    resolve({
      ok: true,
      json: async () => ({ language: "zh", response_language: "zh" }),
    } as Response);
  });

  expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBeNull();
  expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBeNull();
});
