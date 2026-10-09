import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { initI18n } from "@/i18n/init";
import WatchingTranscriptRedirect from "@/components/reading/WatchingTranscriptRedirect";

const { importReadingUrls, replace } = vi.hoisted(() => ({
  importReadingUrls: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/reading-workspace-api", () => ({ importReadingUrls }));
vi.mock("@/lib/learning-routes", () => ({
  readingCollectionRoute: (workspaceId: string) => `/learning/reading/${workspaceId}`,
}));

initI18n("en");

describe("WatchingTranscriptRedirect", () => {
  beforeEach(() => vi.clearAllMocks());

  it("imports the video into Immersive Reading and opens its transcript workspace", async () => {
    importReadingUrls.mockResolvedValue({
      materials: [],
      workspace: { workspace_id: "rw_lecture_1" },
    });

    render(
      <WatchingTranscriptRedirect
        sourceUrl="https://www.youtube.com/watch?v=114i2Kz-LZA"
        title="Lecture 1: Transformers"
      />,
    );

    await waitFor(() =>
      expect(importReadingUrls).toHaveBeenCalledWith({
        urls: ["https://www.youtube.com/watch?v=114i2Kz-LZA"],
        workspace_title: "Lecture 1: Transformers transcript",
      }),
    );
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/learning/reading/rw_lecture_1"),
    );
  });
});
