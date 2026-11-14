import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import ToolsSettingsPage from "@/features/settings/sections/ToolsSettingsSection";

const t = (key: string) => (({ "Search the web": "Rechercher sur le web", "Use for current facts": "Pour les faits actuels" } as Record<string, string>)[key]) ?? key;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t }) }));
vi.mock("@/features/settings/store/SettingsStore", () => ({ useSettings: () => ({ language: "fr", draftRevision: 0 }) }));
vi.mock("@/features/settings/store/useStagedSettings", () => ({ useStagedSettings: (_key: string, value: unknown) => [value, vi.fn()] }));
vi.mock("@/components/settings/shared", () => ({ SettingsPageHeader: () => null }));
vi.mock("@/shared/ui/Tooltip", () => ({ default: ({ children }: {children: React.ReactNode}) => children }));
vi.mock("@/lib/api", () => ({ apiUrl: (s: string) => s, apiFetch: async () => ({ ok: true, json: async () => ({ tools: [{ name: "web_search", description: "search", parameters: [], aliases: [], enabled: false, toggleable: true, hints: { en: { short_description: "Search the web", when_to_use: "Use for current facts", input_format: "A plain query", guideline: "", note: "", phase: "", aliases: [] } } }], enabled_optional_tools: [] }) }) }));

it("translates API hints through the selected catalog, searches them, and keeps missing English fallbacks", async () => {
  render(<ToolsSettingsPage />);
  await screen.findByText("Rechercher sur le web");
  fireEvent.change(screen.getByLabelText("Search tools"), { target: { value: "faits actuels" } });
  fireEvent.click(screen.getByRole("button", { name: /web_search/ }));
  expect(screen.getByText("Pour les faits actuels")).toBeTruthy();
  expect(screen.getByText("A plain query")).toBeTruthy();
});
