import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import SettingsOverview from "@/components/settings/SettingsOverview";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
  apiUrl: (path: string) => path,
}));
vi.mock("@/features/settings/store/SettingsStore", () => ({
  useSettings: () => ({ catalogEditable: true }),
}));
vi.mock("@/features/settings/store", () => ({
  RESPONSE_LANGUAGE_OPTIONS: [{ value: "en", label: "English" }],
  useUiSettings: () => ({
    language: "en",
    responseLanguage: "en",
    updateLanguage: vi.fn(),
    updateResponseLanguage: vi.fn(),
  }),
}));
vi.mock("@/features/settings/store/useStagedSettings", () => ({
  useStagedSettings: () => ["modern", vi.fn()],
}));
vi.mock("@/hooks/useUiLayout", () => ({
  useUiLayout: () => "modern",
}));
vi.mock("@/components/settings/AgentSetupHelp", () => ({
  default: () => null,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      key.replace(/{{(\w+)}}/g, (_, name) => String(values?.[name] ?? name)),
  }),
}));

beforeEach(() => {
  mocks.fetch.mockReset();
  mocks.fetch.mockResolvedValue({ ok: false, status: 500 });
});

it("requires confirmation and reports a failed configuration reset", async () => {
  render(<SettingsOverview />);

  fireEvent.click(
    screen.getByRole("button", { name: "Reset all configurations" }),
  );
  expect(screen.getByRole("alertdialog")).toHaveTextContent(
    "Your account and learning data will remain.",
  );

  fireEvent.click(
    screen.getByRole("button", { name: "Reset configurations" }),
  );

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Could not reset configurations (HTTP 500).",
    );
  });
  expect(mocks.fetch).toHaveBeenCalledWith(
    "/api/settings/reset",
    expect.objectContaining({ method: "POST" }),
  );
});
