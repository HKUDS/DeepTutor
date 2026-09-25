import { act, cleanup, render } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, expect, it, vi } from "vitest";
import LazySessionViewerPanel, {
  type SessionViewerPanelHandle,
} from "@/components/chat/home/LazySessionViewerPanel";
import type { SessionViewerPanelProps } from "@/components/chat/home/SessionViewerPanel";

const fixture = vi.hoisted(() => ({
  ready: false,
  mounts: 0,
  unmounts: 0,
  calls: [] as string[],
}));

vi.mock("next/dynamic", async () => {
  const { forwardRef, useEffect, useImperativeHandle } = await import("react");
  const LoadedPanel = forwardRef<SessionViewerPanelHandle>(function LoadedPanel(
    _props,
    ref,
  ) {
    useImperativeHandle(ref, () => ({
      openFileTab: () => fixture.calls.push("file"),
      openWebTab: (url) => fixture.calls.push(url),
      openMarkdownNoteTab: () => fixture.calls.push("markdown"),
      openQuizFollowupTab: () => fixture.calls.push("quiz"),
      openSelectionTutorTab: () => fixture.calls.push("selection"),
      openGeogebraTab: () => fixture.calls.push("geogebra"),
      openSubagentTab: () => fixture.calls.push("subagent"),
      focusActivityHome: () => fixture.calls.push("activity"),
    }));
    return null;
  });
  return {
    default: () =>
      forwardRef<SessionViewerPanelHandle>(function DeferredPanel(_props, ref) {
        useEffect(() => {
          fixture.mounts += 1;
          return () => {
            fixture.unmounts += 1;
          };
        }, []);
        return fixture.ready ? <LoadedPanel ref={ref} /> : null;
      }),
  };
});

afterEach(() => {
  cleanup();
  fixture.ready = false;
  fixture.mounts = 0;
  fixture.unmounts = 0;
  fixture.calls = [];
});

it("does not mount the viewer while closed and idle", () => {
  render(
    <LazySessionViewerPanel
      open={false}
      sessionId="session-a"
      activity={{} as SessionViewerPanelProps["activity"]}
      onClose={() => {}}
      onAutoOpen={() => {}}
    />,
  );
  expect(fixture.mounts).toBe(0);
});

it("replays viewer actions in order when the chunk loads", () => {
  const ref = createRef<SessionViewerPanelHandle>();
  const props = {
    open: false,
    sessionId: "session-a",
    activity: {} as SessionViewerPanelProps["activity"],
    onClose: () => {},
    onAutoOpen: () => {},
  };
  const view = render(<LazySessionViewerPanel {...props} ref={ref} />);
  expect(fixture.mounts).toBe(0);

  act(() => {
    ref.current?.openWebTab("https://example.com");
    ref.current?.focusActivityHome();
  });
  expect(fixture.calls).toEqual([]);
  expect(fixture.mounts).toBeGreaterThan(0);

  fixture.ready = true;
  view.rerender(<LazySessionViewerPanel {...props} ref={ref} />);
  expect(fixture.calls).toEqual(["https://example.com", "activity"]);
});

it("drops queued actions from the previous session", () => {
  const ref = createRef<SessionViewerPanelHandle>();
  const props = {
    open: false,
    sessionId: "session-a",
    activity: {} as SessionViewerPanelProps["activity"],
    onClose: () => {},
    onAutoOpen: () => {},
  };
  const view = render(<LazySessionViewerPanel {...props} ref={ref} />);
  act(() => ref.current?.openWebTab("stale"));
  view.rerender(<LazySessionViewerPanel {...props} sessionId="session-b" ref={ref} />);
  act(() => ref.current?.openWebTab("current"));

  fixture.ready = true;
  view.rerender(<LazySessionViewerPanel {...props} sessionId="session-b" ref={ref} />);
  expect(fixture.calls).toEqual(["current"]);
});

it("stays mounted after closing so the slide-out can play", () => {
  const props = {
    open: true,
    sessionId: "session-a",
    activity: {} as SessionViewerPanelProps["activity"],
    onClose: () => {},
    onAutoOpen: () => {},
  };
  const view = render(<LazySessionViewerPanel {...props} />);
  expect(fixture.mounts).toBe(1);

  view.rerender(<LazySessionViewerPanel {...props} open={false} />);
  expect(fixture.unmounts).toBe(0);
});
