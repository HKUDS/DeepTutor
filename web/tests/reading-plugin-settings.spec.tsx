import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import ReadingPluginsSettingsSection from "@/features/settings/sections/ReadingPluginsSettingsSection";
import { apiFetch } from "@/lib/api";
vi.mock("@/lib/api", () => ({
  apiUrl: (path: string) => path,
  apiFetch: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (value: string) => value }),
}));
const bundled = { mode: "builtin", disabled: [] };
const initial = {
  package: "deeptutor-reading-extensions",
  desired: bundled,
  active: bundled,
  restart_required: false,
  extensions: ["read_aloud", "vocabulary", "quiz"],
};
beforeEach(() => {
  vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify(initial)));
});

test("install requires trusting the publisher and shows restart state", async () => {
  render(<ReadingPluginsSettingsSection />);
  await screen.findByText("Active reading version", { exact: false });
  const download = screen.getByRole("button", {
    name: "Download or update reading bundle",
  });
  expect(download).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /I trust/ }));
  vi.mocked(apiFetch).mockResolvedValue(
    new Response(
      JSON.stringify({
        ...initial,
        desired: { ...bundled, mode: "managed", version: "0.1.0" },
        restart_required: true,
      }),
    ),
  );
  fireEvent.click(download);
  expect(
    await screen.findByText(
      "Restart all DeepTutor backend workers to apply these changes.",
    ),
  ).toBeVisible();
  expect(apiFetch).toHaveBeenLastCalledWith("/api/reading/plugins/download", {
    method: "POST",
  });
});

test("action switches preserve separate control", async () => {
  render(<ReadingPluginsSettingsSection />);
  const vocabulary = await screen.findByRole("checkbox", {
    name: "Look up word",
  });
  vi.mocked(apiFetch).mockResolvedValue(
    new Response(
      JSON.stringify({
        ...initial,
        desired: { ...bundled, disabled: ["vocabulary"] },
        restart_required: true,
      }),
    ),
  );
  fireEvent.click(vocabulary);
  await waitFor(() =>
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/reading/plugins/vocabulary/enabled",
      expect.objectContaining({ method: "PUT", body: '{"enabled":false}' }),
    ),
  );
});

test("download failures stay visible with retry", async () => {
  vi.mocked(apiFetch).mockResolvedValue(
    new Response(JSON.stringify({ detail: "Offline" }), { status: 400 }),
  );
  render(<ReadingPluginsSettingsSection />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Offline");
  expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
});

test("installed providers require explicit selection", async () => {
  const state = {
    packages: {
      "deeptutor-reading-dictionary-example": {
        name: "Dictionary example",
        version: "0.2.0",
        targets: { vocabulary: "example:Provider" },
      },
    },
    providers: {},
  };
  const catalog = {
    ...initial,
    components: { active: state, desired: state, errors: {} },
  };
  vi.mocked(apiFetch).mockImplementation(
    async () => new Response(JSON.stringify(catalog)),
  );
  render(<ReadingPluginsSettingsSection />);
  const selector = await screen.findByRole("combobox", {
    name: "Provider: Look up word",
  });
  expect(selector).toHaveValue("");
  fireEvent.change(selector, {
    target: { value: "deeptutor-reading-dictionary-example" },
  });
  await waitFor(() =>
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/reading/plugins/providers/vocabulary",
      expect.objectContaining({
        method: "PUT",
        body: '{"package":"deeptutor-reading-dictionary-example"}',
      }),
    ),
  );
});
