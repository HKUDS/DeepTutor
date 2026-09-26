import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import AssetPicker from "@/components/partners/AssetPicker";
import PartnerWorkspacePicker from "@/components/partners/PartnerWorkspacePicker";

const fixture = vi.hoisted(() => ({ workspaces: vi.fn(), kbs: vi.fn() }));
vi.mock("@/lib/workspaces-api", async (original) => ({
  ...(await original<object>()),
  listWorkspaces: fixture.workspaces,
}));
vi.mock("@/features/knowledge/api/catalog", () => ({
  listKnowledgeBases: fixture.kbs,
}));
vi.mock("@/lib/skills-api", () => ({ listSkills: async () => [] }));
vi.mock("@/lib/notebook-api", () => ({ listNotebooks: async () => [] }));
const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));
afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

it("offers only ready shared workspaces and allows returning to private storage", async () => {
  fixture.workspaces.mockResolvedValue([
    {
      workspace_id: "general",
      display_name: "General",
      kind: "general",
      status: "ready",
    },
    {
      workspace_id: "research",
      display_name: "Research",
      kind: "workspace",
      status: "ready",
    },
    {
      workspace_id: "system",
      display_name: "System",
      kind: "system",
      status: "ready",
    },
    {
      workspace_id: "old",
      display_name: "Archived",
      kind: "workspace",
      status: "ready",
      archived: true,
    },
    {
      workspace_id: "missing",
      display_name: "Missing",
      kind: "workspace",
      status: "invalid",
    },
  ]);
  function Picker() {
    const [value, setValue] = useState("");
    return <PartnerWorkspacePicker value={value} onChange={setValue} />;
  }
  render(<Picker />);
  await screen.findByRole("option", { name: "Research" });
  expect(
    screen.queryByRole("option", { name: "System" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("option", { name: "Archived" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("option", { name: "Missing" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Workspace" }), {
    target: { value: "research" },
  });
  expect(screen.getByRole("combobox")).toHaveValue("research");
  expect(screen.getByText(/Changes stay in sync/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "" } });
  expect(screen.getByRole("combobox")).toHaveValue("");
});

it("keeps an unavailable binding visible and reports loading errors with retry", async () => {
  fixture.workspaces
    .mockRejectedValueOnce(new Error("Network unavailable"))
    .mockResolvedValue([]);
  render(<PartnerWorkspacePicker value="gone" onChange={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Network unavailable",
  );
  expect(screen.getByRole("combobox")).toHaveValue("gone");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() =>
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
  );
  expect(
    await screen.findByRole("option", {
      name: "Assigned workspace unavailable",
    }),
  ).toBeInTheDocument();
});

it("excludes subagents and non-retrievable connections while keeping real remote knowledge bases", async () => {
  fixture.kbs.mockResolvedValue([
    { name: "Textbook" },
    { name: "Remote library", metadata: { type: "weknora" } },
    { name: "Panda Kate", metadata: { type: "subagent" } },
    { name: "Vault", metadata: { type: "obsidian" } },
    { name: "MarginNote", metadata: { type: "marginnote4" } },
    { name: "Unavailable", available: false },
  ]);
  const onChange = vi.fn();
  render(
    <AssetPicker
      value={{ knowledge_bases: [], skills: [], notebooks: [] }}
      onChange={onChange}
    />,
  );
  await screen.findByRole("button", { name: "Textbook" });
  expect(
    screen.getByRole("button", { name: "Remote library" }),
  ).toBeInTheDocument();
  for (const name of ["Panda Kate", "Vault", "MarginNote", "Unavailable"]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
  fireEvent.click(screen.getByRole("button", { name: "Textbook" }));
  expect(onChange).toHaveBeenCalledWith({
    knowledge_bases: ["Textbook"],
    skills: [],
    notebooks: [],
  });
});
