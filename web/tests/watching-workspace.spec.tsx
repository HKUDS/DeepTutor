import React, { useEffect } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WatchingProvider, useWatching } from "@/context/WatchingContext";
import { WatchingSessionBridge } from "@/components/watching/WatchingWorkspace";
import { watchingTurnFields } from "@/lib/watching-turn-state";
import type { TimedMediaMaterial } from "@/lib/video-learning-api";

const api = vi.hoisted(() => ({ get: vi.fn(), resolve: vi.fn() }));
vi.mock("@/lib/video-learning-api", () => ({
  getVideoMaterial: api.get,
  resolveVideo: api.resolve,
  refreshInvidiousTranscript: vi.fn(),
}));
const translate = (key: string) => key;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: translate }) }));
vi.mock("@/components/watching/WatchingPane", () => ({
  WatchingPane: () => null,
  WATCHING_ASK_EVENT: "dt:watching-ask",
}));

function material(id: string): TimedMediaMaterial {
  return {
    material_id: id,
    source: { url: id },
    playback: { start_seconds: 37 },
    learning: { last_position: 37 },
  } as TimedMediaMaterial;
}
let context: ReturnType<typeof useWatching>;
function Probe() {
  const current = useWatching();
  useEffect(() => {
    context = current;
  }, [current]);
  return <span>{current.material?.material_id || "empty"}</span>;
}
function App({ scope, id }: { scope: string; id: string | null }) {
  return (
    <WatchingProvider>
      <WatchingSessionBridge
        sessionKey={scope}
        materialId={id}
        onMaterial={vi.fn()}
      />
      <Probe />
    </WatchingProvider>
  );
}

describe("Watching conversation restoration", () => {
  it("ignores browser-global video history and does not fetch on ordinary provider mount", () => {
    api.get.mockClear();
    localStorage.setItem("dt:video-learning:last-material", "other-owner");
    render(
      <WatchingProvider>
        <Probe />
      </WatchingProvider>,
    );
    expect(api.get).not.toHaveBeenCalled();
    expect(screen.getByText("empty")).toBeInTheDocument();
  });

  it("drops a late previous-session result and restores the new video's saved position", async () => {
    let finishA!: (value: TimedMediaMaterial) => void;
    api.get.mockImplementation((id: string) =>
      id === "a"
        ? new Promise((resolve) => {
            finishA = resolve;
          })
        : Promise.resolve(material(id)),
    );
    const view = render(<App scope="session-a" id="a" />);
    view.rerender(<App scope="session-b" id="b" />);
    await screen.findByText("b");
    await act(async () => {
      finishA(material("a"));
    });
    expect(screen.getByText("b")).toBeInTheDocument();
    expect(watchingTurnFields("immersive_watching")).toEqual({
      timed_media_id: "b",
      timed_media_viewport: { time_seconds: 37 },
    });
    expect(watchingTurnFields("chat")).toEqual({});
    view.unmount();
    expect(watchingTurnFields("immersive_watching")).toEqual({});
  });

  it("clears the previous video on unavailable or unauthorized materials", async () => {
    api.get
      .mockResolvedValueOnce(material("a"))
      .mockRejectedValueOnce(new Error("Not found"));
    const view = render(<App scope="session-a" id="a" />);
    await screen.findByText("a");
    view.rerender(<App scope="session-b" id="private-b" />);
    await waitFor(() => expect(context.error).toBe("Not found"));
    expect(screen.getByText("empty")).toBeInTheDocument();
    expect(watchingTurnFields("immersive_watching")).toEqual({});
  });

  it("invalidates an open request when leaving the workspace", async () => {
    let finish!: (value: TimedMediaMaterial) => void;
    api.resolve.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const view = render(<App scope="draft" id={null} />);
    await act(async () => {});
    let opening!: Promise<void>;
    act(() => {
      opening = context.openUrl("video");
    });
    view.unmount();
    await act(async () => {
      finish(material("late"));
      await opening;
    });
    expect(watchingTurnFields("immersive_watching")).toEqual({});
  });
});
