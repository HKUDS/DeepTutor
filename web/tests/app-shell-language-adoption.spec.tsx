import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AppShellProvider, useAppShell } from "@/context/AppShellContext";
import {
  LANGUAGE_STORAGE_KEY,
  RESPONSE_LANGUAGE_STORAGE_KEY,
} from "@/context/app-shell-storage";
import { apiFetch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  apiUrl: (path: string) => path,
}));

function LanguageProbe() {
  const { language, languageReady } = useAppShell();
  return <output data-testid="language" data-ready={languageReady}>{language}</output>;
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(apiFetch).mockReset();
  vi.mocked(apiFetch).mockResolvedValue({
    ok: true,
    json: async () => ({ language: "uk", response_language: "fr" }),
  } as Response);
});

afterEach(() => cleanup());

it("adopts Ukrainian UI and French output preferences from the server on a new browser", async () => {
  render(<AppShellProvider><LanguageProbe /></AppShellProvider>);

  await waitFor(() => {
    expect(screen.getByTestId("language")).toHaveTextContent("uk");
    expect(screen.getByTestId("language")).toHaveAttribute("data-ready", "true");
  });
  expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("uk");
  expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBe("fr");
});

it("keeps a browser's French UI choice while adopting its missing output preference", async () => {
  localStorage.setItem(LANGUAGE_STORAGE_KEY, "fr");
  vi.mocked(apiFetch).mockResolvedValue({
    ok: true,
    json: async () => ({ language: "uk", response_language: "uk" }),
  } as Response);
  render(<AppShellProvider><LanguageProbe /></AppShellProvider>);

  await waitFor(() => {
    expect(screen.getByTestId("language")).toHaveTextContent("fr");
    expect(screen.getByTestId("language")).toHaveAttribute("data-ready", "true");
  });
  expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("fr");
  expect(localStorage.getItem(RESPONSE_LANGUAGE_STORAGE_KEY)).toBe("uk");
});
