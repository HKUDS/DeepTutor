import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";
import type { PointLecture } from "@/lib/learning-api";

const fetchPointLecture = vi.fn();
const rollPointLectureDraft = vi.fn();

vi.mock("@/lib/learning-api", () => ({
  fetchPointLecture: (...args: unknown[]) => fetchPointLecture(...args),
  rollPointLectureDraft: (...args: unknown[]) => rollPointLectureDraft(...args),
  confirmPointLecture: vi.fn(),
  discardPointLectureDraft: vi.fn(),
  revertPointLecture: vi.fn(),
  savePointLecture: vi.fn(),
}));

// Imported after the mock so the component binds the mocked client.
import { LectureReaderPane } from "@/components/space/learning/LectureReaderPane";

initI18n("en");

function lecture(body: string, overrides: Partial<PointLecture> = {}): PointLecture {
  return {
    body,
    confirmed_body: "",
    status: "draft_only",
    revision: 0,
    source: "",
    confirmed_at: 0,
    covered_message_id: 1,
    latest_message_id: 1,
    has_study: true,
    stale: false,
    stale_from_study: false,
    draft: {
      session_id: "s1",
      body,
      diff: [],
      base_revision: 0,
      covered_message_id: 1,
      origin: "study_roll",
      updated_at: 1,
    },
    ...overrides,
  };
}

describe("LectureReaderPane force rewrite", () => {
  beforeEach(() => {
    fetchPointLecture.mockReset();
    rollPointLectureDraft.mockReset();
  });

  it("rewrites the draft from the whole conversation when asked", async () => {
    fetchPointLecture
      .mockResolvedValueOnce(lecture("# Concept\n\nOld text."))
      .mockResolvedValueOnce(lecture("# Concept\n\nRewritten text."));
    rollPointLectureDraft.mockResolvedValue(lecture("# Concept\n\nRewritten text."));

    render(<LectureReaderPane pathId="p1" knowledgePointId="kp1" />);

    const button = await screen.findByRole("button", { name: "Force rewrite lecture" });
    await userEvent.click(button);

    expect(rollPointLectureDraft).toHaveBeenCalledWith("p1", "kp1", { force: true });
    await waitFor(() =>
      expect(screen.getByText("Rewritten text.")).toBeInTheDocument(),
    );
  });

  it("does not offer the rewrite before there is anything to rewrite", async () => {
    fetchPointLecture.mockResolvedValue(
      lecture("", { status: "none", draft: null, has_study: false }),
    );

    render(<LectureReaderPane pathId="p1" knowledgePointId="kp1" />);

    await screen.findByText("No lecture yet for this knowledge point.");
    expect(screen.queryByRole("button", { name: "Force rewrite lecture" })).toBeNull();
  });
});
