import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentSetupHelp from "@/components/settings/AgentSetupHelp";
import { copyText } from "@/lib/clipboard";
import en from "@/locales/en/app.json";
import zh from "@/locales/zh/app.json";

let locale: Record<string, string> = en;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => locale[key] ?? key }),
}));
vi.mock("@/lib/clipboard", () => ({ copyText: vi.fn() }));

beforeEach(() => {
  locale = en;
  vi.mocked(copyText).mockReset();
});

describe("Agent setup handoff", () => {
  it("copies the complete displayed guide and restores focus on Escape", async () => {
    vi.mocked(copyText).mockResolvedValue(undefined);
    render(<AgentSetupHelp />);
    const trigger = screen.getByRole("button", { name: en["settings.agentSetup.title"] });
    trigger.focus();
    fireEvent.click(trigger);
    const prompt = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(prompt).toHaveAttribute("readonly");
    expect(prompt.value).toContain("docs-for-user/AGENT_SETUP.md");
    expect(prompt.value).toContain("existing DeepTutor installation");
    expect(prompt.value).toContain("pending drafts");
    fireEvent.click(screen.getByRole("button", { name: en["settings.agentSetup.copy"] }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(en.Copied));
    expect(copyText).toHaveBeenCalledWith(prompt.value);
    fireEvent.keyDown(prompt, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("keeps the prompt selectable and allows retry when clipboard access fails", async () => {
    vi.mocked(copyText).mockRejectedValueOnce(new Error("Clipboard blocked"));
    render(<AgentSetupHelp />);
    fireEvent.click(screen.getByRole("button", { name: en["settings.agentSetup.title"] }));
    const copy = screen.getByRole("button", { name: en["settings.agentSetup.copy"] });
    fireEvent.click(copy);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(en["settings.agentSetup.copyFailed"]));
    const prompt = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.focus(prompt);
    expect(prompt.selectionEnd - prompt.selectionStart).toBe(prompt.value.length);
    vi.mocked(copyText).mockResolvedValueOnce(undefined);
    fireEvent.click(copy);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(en.Copied));
  });

  it("shows and copies the Chinese prompt when the interface is Chinese", async () => {
    locale = zh;
    vi.mocked(copyText).mockResolvedValue(undefined);
    render(<AgentSetupHelp />);
    fireEvent.click(screen.getByRole("button", { name: zh["settings.agentSetup.title"] }));
    expect(screen.getByRole("textbox")).toHaveValue(zh["settings.agentSetup.prompt"]);
    fireEvent.click(screen.getByRole("button", { name: zh["settings.agentSetup.copy"] }));
    await waitFor(() => expect(copyText).toHaveBeenCalledWith(zh["settings.agentSetup.prompt"]));
  });
});
