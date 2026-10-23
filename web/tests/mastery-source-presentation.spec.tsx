import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { MasterySourcePresentation } from "@/components/chat/home/MasterySourcePresentation";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ apiFetch, apiUrl: (url: string) => url }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

const preview = "/api/knowledge-bases/course/source-page?document=lecture.pdf&page=7&digest=abc";
function event(sources: unknown[]): StreamEvent {
  return { type: "sources", source: "chat", stage: "responding", content: "",
    timestamp: 1, metadata: { sources } };
}

beforeEach(() => {
  apiFetch.mockReset().mockResolvedValue({ ok: true, headers: new Headers(),
    arrayBuffer: async () => new ArrayBuffer(4) });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:source-page");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
});

describe("Explicit Mastery source presentation", () => {
  it.each(["teaching", "reveal"])("renders authenticated %s pages from shared-loop events and replay", async presentation => {
    const sources = event([{ title: "Lecture page 7", preview_url: preview, presentation }]);
    const { rerender, unmount } = render(<MasterySourcePresentation events={[sources, sources]} />);
    expect(await screen.findByRole("img", { name: "Lecture page 7" })).toHaveAttribute("src", "blob:source-page");
    expect(apiFetch).toHaveBeenCalledWith(preview, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    rerender(<MasterySourcePresentation events={[sources]} />);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:source-page");
  });

  it("never fetches private, denied, legacy, external, or non-source rows", () => {
    const marked = { title: "Page", presentation: "teaching", preview_url: preview };
    const wrongType = { ...event([marked]), type: "tool_result" } as StreamEvent;
    render(<MasterySourcePresentation events={[wrongType, event([
      { ...marked, presentation: undefined }, { ...marked, presentation: "inspect" },
      { ...marked, presentation: "denied" }, { ...marked, preview_url: "https://tracker.invalid/pixel" },
      { ...marked, preview_url: "//tracker.invalid/pixel" },
      { ...marked, preview_url: "/api/knowledge-bases/course/../source-page?page=1" },
      { ...marked, preview_url: "/api/knowledge-bases/course/source-page/extra?page=1" },
    ])]} />);
    expect(apiFetch).not.toHaveBeenCalled();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("shows a failed authenticated fetch without exposing a direct image URL", async () => {
    apiFetch.mockResolvedValue({ ok: false, status: 403 });
    render(<MasterySourcePresentation events={[event([{ title: "Page", presentation: "teaching", preview_url: preview }])]} />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Failed to load image."));
    expect(screen.queryByRole("img")).toBeNull();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("does not allocate an image URL when a response finishes after unmount", async () => {
    let resolve!: (value: ArrayBuffer) => void;
    const bytes = new Promise<ArrayBuffer>(done => { resolve = done; });
    apiFetch.mockResolvedValue({ ok: true, headers: new Headers(), arrayBuffer: () => bytes });
    const { unmount } = render(<MasterySourcePresentation events={[event([
      { title: "Page", presentation: "teaching", preview_url: preview },
    ])]} />);
    await act(async () => {});
    unmount();
    await act(async () => { resolve(new ArrayBuffer(4)); await bytes; });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
