import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import KbWebSourcesSection from "@/components/knowledge/KbWebSourcesSection";
import * as sourcesApi from "@/features/knowledge/api/sources";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

afterEach(cleanup);

it("renders bilingual pairs count when pairings exist", async () => {
  vi.spyOn(sourcesApi, "listWebSources").mockResolvedValue([
    {
      id: "src-1",
      url: "https://example.com/docs/",
      max_depth: 3,
      max_pages: 50,
      enabled: true,
      auto_sync_enabled: true,
      sync_interval_hours: 24,
      page_count: 10,
      last_synced_at: "2026-09-28T12:00:00Z",
      last_sync_status: "success",
      last_sync_error: null,
      added_at: "2026-09-28T10:00:00Z",
      bilingual_pairings: [
        {
          pairing_id: "pair-1",
          source_url: "https://example.com/docs/en/intro",
          target_url: "https://example.com/docs/zh/intro",
          source_file: "intro.md",
          target_file: "intro.zh.md",
          source_lang: "en",
          target_lang: "zh",
          pairing_method: "hreflang",
        },
      ],
    },
  ]);
  vi.spyOn(sourcesApi, "listWebSourceSyncJobs").mockResolvedValue([]);

  render(<KbWebSourcesSection kbName="test-kb" />);

  expect(await screen.findByText(/Bilingual pairs: 1/)).toBeDefined();
});
