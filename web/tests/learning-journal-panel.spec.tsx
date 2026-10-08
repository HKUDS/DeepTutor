import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LearningJournalPanel from "@/components/space/LearningJournalPanel";
import { getLearningJournal, type LearningJournal } from "@/lib/learning-journal-api";

const route = vi.hoisted(() => ({ workspace: "a" }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams({ dt_workspace: route.workspace }) }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("@/lib/learning-journal-api", () => ({ getLearningJournal: vi.fn() }));
const empty: LearningJournal = {
  version: 1, updated_at: "", injected_context: "",
  mission: { topic: "", why: "", level: "", updated_at: "" },
  last_session: { summary: "", next_focus: "", updated_at: "" }, records: [],
};

beforeEach(() => { vi.clearAllMocks(); route.workspace = "a"; });
describe("Learning journal overview", () => {
  it("shows the mission, handoff and newest-first records without editing controls", async () => {
    vi.mocked(getLearningJournal).mockResolvedValue({ ...empty,
      mission: { ...empty.mission, topic: "Signals", why: "Exam", level: "Beginner" },
      last_session: { ...empty.last_session, summary: "Sampling", next_focus: "Aliasing" },
      records: [{ id: "new", title: "Newer", insight: "Second", created_at: "" }, { id: "old", title: "Older", insight: "First", created_at: "" }],
    });
    render(<LearningJournalPanel />);
    await screen.findByText("Signals");
    expect(screen.getByText("Sampling")).toBeInTheDocument();
    expect(screen.getByText("Aliasing")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").map((el) => el.textContent)).toEqual(["NewerSecond", "OlderFirst"]);
    expect(screen.queryByRole("textbox")).toBeNull();
  });
  it("explains an empty journal and retries failed reads", async () => {
    vi.mocked(getLearningJournal).mockRejectedValueOnce(new Error("409")).mockResolvedValue(empty);
    render(<LearningJournalPanel />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Your tutor has no mission for you yet. Ask it to set one in conversation.");
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("does not display an old workspace response after switching", async () => {
    let resolve!: (journal: LearningJournal) => void;
    vi.mocked(getLearningJournal).mockImplementationOnce(() => new Promise((done) => { resolve = done; })).mockResolvedValue(empty);
    const view = render(<LearningJournalPanel />);
    route.workspace = "b";
    view.rerender(<LearningJournalPanel />);
    await screen.findByText("No session handoff yet.");
    resolve({ ...empty, mission: { ...empty.mission, topic: "Old workspace secret" } });
    await waitFor(() => expect(screen.queryByText("Old workspace secret")).toBeNull());
  });
});
