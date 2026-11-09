import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import GuardianSettingsPage from "@/features/settings/sections/GuardianSettingsSection";
import { getGuardianReport, listGuardianRelationships, type GuardianReport } from "@/lib/guardian-api";
import { initI18n } from "@/i18n/init";
vi.mock("@/lib/guardian-api", () => ({
  getGuardianReport: vi.fn(), listGuardianRelationships: vi.fn(), getGuardianMaterials: vi.fn(),
  getGuardianRestrictions: vi.fn(), resetLearnerCredentials: vi.fn(), revokeMyGuardianRelationship: vi.fn(),
}));
vi.mock("@/features/settings/store/useStagedSettings", () => ({
  useStagedSettings: <T,>(_key: string, live: T, setLive: (value: T) => void) => [live, setLive],
}));
initI18n("en");
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listGuardianRelationships).mockResolvedValue(["A", "B"].map(id => ({
    id, guardian_user_id: "parent", guardian_username: "Parent", learner_user_id: id,
    learner_username: `Learner ${id}`, permissions: ["view_reports"],
  })));
});
function report(id: string): GuardianReport {
  return {
    learner: { id, username: `Learner ${id}`, disabled: false }, assigned_materials: [],
    grant_summary: { model_count: 0, skill_count: 0, knowledge_base_count: 0 },
    reading: { reading_status: "available", quiz_status: "available", progress_total: 1,
      progress: [{ material_id: id, material_title: `Lesson for ${id}`, latest_locator: 1,
        latest_percentage: 0.2, furthest_locator: 1, furthest_percentage: 0.2, updated_at: 1 }],
      activities: [], quizzes: [], quiz_total: 0, limit: 50 },
  };
}
it("keeps B selected and visible when the older A response arrives last", async () => {
  let finishA!: (value: GuardianReport) => void;
  vi.mocked(getGuardianReport).mockImplementation(id => id === "A"
    ? new Promise(resolve => { finishA = resolve; }) : Promise.resolve(report("B")));
  render(<GuardianSettingsPage />);
  fireEvent.click(await screen.findByRole("button", { name: /Learner A/ }));
  fireEvent.click(screen.getByRole("button", { name: /Learner B/ }));
  await screen.findByText("Lesson for B");
  await act(async () => { finishA(report("A")); });
  expect(screen.queryByText("Lesson for A")).toBeNull();
  expect(screen.getByText("Lesson for B")).toBeTruthy();
});
it("does not fetch or show a report without view_reports", async () => {
  vi.mocked(listGuardianRelationships).mockResolvedValue([{ id: "A", guardian_user_id: "parent",
    guardian_username: "Parent", learner_user_id: "A", learner_username: "Learner A", permissions: [] }]);
  render(<GuardianSettingsPage />);
  fireEvent.click(await screen.findByRole("button", { name: /Learner A/ }));
  await screen.findByText("You are not authorized to view this learner report.");
  expect(getGuardianReport).not.toHaveBeenCalled();
  expect(screen.queryByRole("region", { name: "Reading progress and quiz records" })).toBeNull();
});
it("shows a failed load instead of retaining the previous learner report", async () => {
  vi.mocked(getGuardianReport).mockImplementation(id => id === "A" ? Promise.resolve(report("A")) : Promise.reject(new Error("Synthetic load failure")));
  render(<GuardianSettingsPage />);
  fireEvent.click(await screen.findByRole("button", { name: /Learner A/ }));
  await screen.findByText("Lesson for A");
  fireEvent.click(screen.getByRole("button", { name: /Learner B/ }));
  await waitFor(() => expect(screen.getByText("Synthetic load failure")).toBeTruthy());
  expect(screen.queryByText("Lesson for A")).toBeNull();
});
