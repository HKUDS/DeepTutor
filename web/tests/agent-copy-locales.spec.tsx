import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

import { ensureLanguage, initI18n } from "@/i18n/init";
import ConnectedAgents from "@/components/agents/ConnectedAgents";

vi.mock("next/navigation", () => ({ usePathname: () => "/agents" }));
vi.mock("@/lib/subagents-api", () => ({
  detectSubagents: vi.fn(async () => [
    { kind: "codex", display_name: "Codex", available: true, version: "", detail: "" },
  ]),
  listSubagentConnections: vi.fn(async () => [
    { name: "my-codex", agent_kind: "codex", cwd: "" },
  ]),
  disconnectSubagent: vi.fn(async () => undefined),
  connectSubagent: vi.fn(),
}));

const i18n = initI18n("en");

beforeAll(async () => {
  await ensureLanguage("zh");
  await ensureLanguage("tr");
});

afterEach(async () => {
  vi.restoreAllMocks();
  await act(async () => {
    await i18n.changeLanguage("en");
  });
});

it("interpolates agent names and sync times in Chinese", async () => {
  await i18n.changeLanguage("zh");
  // These used to be template literals in the components; the zh catalog now holds them.
  expect(
    i18n.t(
      "Disconnect “{{name}}”? This only removes the connection; your local agent is untouched.",
      { name: "my-codex" },
    ),
  ).toBe("断开「my-codex」？这只会移除连接，不影响本机的智能体配置。");
  expect(
    i18n.t(
      "Model, reasoning effort, and run parameters DeepTutor drives the local {{name}} with when consulting it. These override the CLI defaults; leave blank to keep the CLI's own default.",
      { name: "Codex" },
    ),
  ).toBe(
    "设置本机 Codex 的模型、推理强度和运行参数。留空使用 CLI 默认值。",
  );
  expect(i18n.t("Last synced: {{when}}", { when: "2026年11月1日" })).toBe(
    "上次同步：2026年11月1日",
  );
});

it("renders connected agents and asks to disconnect in Turkish", async () => {
  await i18n.changeLanguage("tr");
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<ConnectedAgents />);

  const title = i18n.t("Connected agents");
  expect(title).not.toBe("Connected agents");
  expect(await screen.findByText(title)).toBeInTheDocument();

  const disconnect = await screen.findByRole("button", { name: i18n.t("Disconnect") });
  fireEvent.click(disconnect);
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
  const message = confirm.mock.calls[0][0] as string;
  expect(message).toContain("my-codex");
  expect(message).not.toContain("This only removes the connection");
});

it("keeps the Chinese header text unchanged", async () => {
  await i18n.changeLanguage("zh");
  render(<ConnectedAgents />);
  expect(await screen.findByText("连接的智能体")).toBeInTheDocument();
});
