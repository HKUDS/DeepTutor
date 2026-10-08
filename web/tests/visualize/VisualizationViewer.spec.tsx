import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import VisualizationViewer from "@/components/visualize/VisualizationViewer";
import type {
  MathAnimatorResult,
} from "@/lib/math-animator-types";
import type {
  VisualizeCanvasResult,
  VisualizeResult,
} from "@/lib/visualize-types";

const fixture = vi.hoisted(() => ({
  t: (key: string, opts?: Record<string, unknown>) =>
    opts
      ? key.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
          String(opts[name] ?? ""),
        )
      : key,
  mermaidRender: vi.fn(),
  chartInstances: [] as Array<{ config: Record<string, unknown> }>,
  destroyedCharts: 0,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: fixture.t }),
}));

vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: fixture.mermaidRender,
  },
}));

vi.mock("chart.js/auto", async () => {
  return {
    default: class MockChart {
      constructor(_el: unknown, config: Record<string, unknown>) {
        fixture.chartInstances.push({ config });
      }
      destroy() {
        fixture.destroyedCharts += 1;
      }
    },
  };
});

vi.mock("next/dynamic", async () => {
  const React = await import("react");
  return {
    default: (
      loader: () => Promise<{ default: React.ComponentType<unknown> }>,
    ) => {
      const Loaded = React.lazy(loader);
      const DynamicComponent = (props: Record<string, unknown>) =>
        React.createElement(
          React.Suspense,
          { fallback: null },
          React.createElement(Loaded, props),
        );
      return DynamicComponent;
    },
  };
});

vi.mock("@/components/math-animator/MathAnimatorViewer", async () => {
  const React = await import("react");
  return {
    default: (props: { result: MathAnimatorResult }) =>
      React.createElement(
        "div",
        { "data-testid": "math-animator-stub" },
        props.result.output_mode,
      ),
  };
});

vi.mock("@/components/Geogebra", async () => {
  const React = await import("react");
  return {
    default: (props: { title?: string }) =>
      React.createElement(
        "div",
        { "data-testid": "geogebra-stub" },
        props.title ?? "",
      ),
  };
});

// The Mermaid child debounces renders by 600ms; fake timers let tests step
// past it deterministically.
const MERMAID_DEBOUNCE_MS = 700;

async function renderPastMermaidDebounce(result: VisualizeResult) {
  vi.useFakeTimers();
  const utils = render(<VisualizationViewer result={result} />);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(MERMAID_DEBOUNCE_MS);
  });
  return utils;
}

function canvasResult(
  overrides: Partial<VisualizeCanvasResult> = {},
): VisualizeCanvasResult {
  return {
    schema_version: "deeptutor.visualization/v1",
    response: "",
    render_type: "mermaid",
    renderer: {
      id: "mermaid",
      version: "1.0.0",
      target: "native",
      native_renderer: "mermaid",
      entry_url: "",
    },
    payload: { format: "text/plain", data: "graph TD;A-->B" },
    presentation: {
      title: "Flow",
      description: "",
      alt_text: "",
      aspect_ratio: "",
    },
    interaction: { events: [] },
    fallback: {},
    code: { language: "mermaid", content: "graph TD;A-->B" },
    analysis: {
      render_type: "mermaid",
      description: "",
      data_description: "",
      chart_type: "flowchart",
      visual_elements: [],
      rationale: "",
    },
    review: { optimized_code: "", changed: false, review_notes: "" },
    ...overrides,
  };
}

const manimResult: VisualizeResult = {
  render_type: "manim_video",
  manim: {
    response: "",
    output_mode: "video",
    code: { language: "python", content: "scene = Scene()" },
    artifacts: [
      {
        type: "video",
        url: "https://example.test/scene.mp4",
        filename: "scene.mp4",
      },
    ],
    timings: {},
    render: {},
  },
};

beforeEach(() => {
  fixture.chartInstances.length = 0;
  fixture.destroyedCharts = 0;
});

afterEach(() => {
  vi.useRealTimers();
});

it("shows a loading placeholder while the mermaid diagram is pending", async () => {
  vi.useFakeTimers();
  render(<VisualizationViewer result={canvasResult()} />);
  expect(screen.getByText("Rendering diagram...")).toBeInTheDocument();
  expect(fixture.mermaidRender).not.toHaveBeenCalled();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(MERMAID_DEBOUNCE_MS);
  });
});

it("renders a valid mermaid chart and hides the loading state", async () => {
  fixture.mermaidRender.mockResolvedValue({
    svg: '<svg data-testid="mermaid-output"><g /></svg>',
  });
  await renderPastMermaidDebounce(canvasResult());

  expect(screen.getByTestId("mermaid-output")).toBeInTheDocument();
  expect(screen.queryByText("Rendering diagram...")).not.toBeInTheDocument();
  expect(screen.queryByText("Diagram rendering error")).not.toBeInTheDocument();
  expect(fixture.mermaidRender).toHaveBeenCalledWith(
    expect.stringContaining("mermaid-"),
    "graph TD;A-->B",
  );
  expect(screen.getByText("Mermaid · flowchart")).toBeInTheDocument();
});

it("renders an error fallback when mermaid rejects invalid syntax", async () => {
  fixture.mermaidRender.mockRejectedValue(new Error("Syntax error in text"));
  await renderPastMermaidDebounce(canvasResult());

  expect(screen.getByText("Diagram rendering error")).toBeInTheDocument();
  expect(screen.getByText("Syntax error in text")).toBeInTheDocument();
  expect(screen.getByText("graph TD;A-->B")).toBeInTheDocument();
  expect(screen.queryByTestId("mermaid-output")).not.toBeInTheDocument();
});

it("never calls mermaid for empty chart content and shows no error", async () => {
  await renderPastMermaidDebounce(
    canvasResult({
      payload: { format: "text/plain", data: "" },
      code: { language: "mermaid", content: "" },
    }),
  );

  expect(fixture.mermaidRender).not.toHaveBeenCalled();
  expect(screen.queryByText("Rendering diagram...")).not.toBeInTheDocument();
  expect(screen.queryByText("Diagram rendering error")).not.toBeInTheDocument();
});

it("toggles the code panel with the source and language", () => {
  render(<VisualizationViewer result={canvasResult()} />);
  expect(screen.queryByText("Hide code")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Show code" }));
  expect(screen.getByText("Hide code")).toBeInTheDocument();
  expect(screen.getByText("mermaid")).toBeInTheDocument();
  expect(screen.getByText("graph TD;A-->B")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Hide code" }));
  expect(screen.queryByText("graph TD;A-->B")).not.toBeInTheDocument();
});

it("copies the chart source to the clipboard", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  try {
    render(<VisualizationViewer result={canvasResult()} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy code" }));
    await waitFor(() =>
      expect(screen.getByText("Copied")).toBeInTheDocument(),
    );
    expect(writeText).toHaveBeenCalledWith("graph TD;A-->B");
  } finally {
    Reflect.deleteProperty(navigator, "clipboard");
  }
});

it("opens a fullscreen overlay and closes it on Escape", () => {
  render(<VisualizationViewer result={canvasResult()} />);
  fireEvent.click(screen.getByRole("button", { name: "Fullscreen" }));

  const closeButtons = screen.getAllByRole("button", { name: "Close" });
  expect(closeButtons).toHaveLength(1);
  expect(
    screen.getAllByText("Mermaid · flowchart").length,
  ).toBeGreaterThanOrEqual(2);
  expect(document.body.style.overflow).toBe("hidden");

  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
  expect(document.body.style.overflow).not.toBe("hidden");
});

it("shows review notes when the review changed the output", () => {
  render(
    <VisualizationViewer
      result={canvasResult({
        review: {
          optimized_code: "",
          changed: true,
          review_notes: "colors adjusted for contrast",
        },
      })}
    />,
  );
  expect(
    screen.getByText("Review: colors adjusted for contrast"),
  ).toBeInTheDocument();
});

it("renders sanitized inline svg with scripts stripped", () => {
  const { container } = render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "svg",
        renderer: {
          id: "svg",
          version: "1.0.0",
          target: "native",
          native_renderer: "svg",
          entry_url: "",
        },
        code: {
          language: "svg",
          content:
            '<svg id="arrow-1"><script>alert(1)</script><circle r="4" /></svg>',
        },
      })}
    />,
  );

  const svg = container.querySelector(".dt-svg-root svg");
  expect(svg).toBeInTheDocument();
  expect(container.querySelector("script")).not.toBeInTheDocument();
});

it("shows an error card for content that is not svg", () => {
  render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "svg",
        renderer: {
          id: "svg",
          version: "1.0.0",
          target: "native",
          native_renderer: "svg",
          entry_url: "",
        },
        code: { language: "svg", content: "plain text, not a figure" },
      })}
    />,
  );
  expect(screen.getByText("SVG rendering error")).toBeInTheDocument();
  expect(
    screen.getByText("Invalid SVG: does not start with <svg"),
  ).toBeInTheDocument();
});

it("splits concatenated svg blocks into separate figures", () => {
  const { container } = render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "svg",
        renderer: {
          id: "svg",
          version: "1.0.0",
          target: "native",
          native_renderer: "svg",
          entry_url: "",
        },
        code: {
          language: "svg",
          content:
            '<svg><circle r="1" /></svg><svg><rect width="2" height="2" /></svg>',
        },
      })}
    />,
  );
  expect(container.querySelectorAll(".dt-svg-root svg")).toHaveLength(2);
});

it("renders a chartjs chart from a parsed JSON config", async () => {
  const config = { type: "bar", data: { labels: ["a"], datasets: [] } };
  render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "chartjs",
        renderer: {
          id: "chartjs",
          version: "1.0.0",
          target: "native",
          native_renderer: "chartjs",
          entry_url: "",
        },
        analysis: {
          render_type: "chartjs",
          description: "",
          data_description: "",
          chart_type: "bar",
          visual_elements: [],
          rationale: "",
        },
        code: { language: "json", content: JSON.stringify(config) },
      })}
    />,
  );

  await waitFor(() => expect(fixture.chartInstances).toHaveLength(1));
  expect(fixture.chartInstances[0].config).toEqual(config);
  expect(screen.getByText("Chart.js · bar")).toBeInTheDocument();
});

it("strips markdown fences before parsing a chartjs config", async () => {
  render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "chartjs",
        renderer: {
          id: "chartjs",
          version: "1.0.0",
          target: "native",
          native_renderer: "chartjs",
          entry_url: "",
        },
        code: {
          language: "json",
          content: '```json\n{"type":"line"}\n```',
        },
      })}
    />,
  );
  await waitFor(() => expect(fixture.chartInstances).toHaveLength(1));
  expect(fixture.chartInstances[0].config).toEqual({ type: "line" });
});

it("shows an error card when the chartjs config cannot be parsed", async () => {
  render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "chartjs",
        renderer: {
          id: "chartjs",
          version: "1.0.0",
          target: "native",
          native_renderer: "chartjs",
          entry_url: "",
        },
        code: { language: "json", content: "{not json at all::" },
      })}
    />,
  );
  expect(await screen.findByText("Chart rendering error")).toBeInTheDocument();
  expect(fixture.chartInstances).toHaveLength(0);
});

it("destroys the chartjs instance on unmount", async () => {
  const { unmount } = render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "chartjs",
        renderer: {
          id: "chartjs",
          version: "1.0.0",
          target: "native",
          native_renderer: "chartjs",
          entry_url: "",
        },
        code: { language: "json", content: '{"type":"bar"}' },
      })}
    />,
  );
  await waitFor(() => expect(fixture.chartInstances).toHaveLength(1));
  unmount();
  expect(fixture.destroyedCharts).toBeGreaterThan(0);
});

it("renders html in a sandboxed iframe and opens it in a new tab", () => {
  const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
  render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "html",
        renderer: {
          id: "html",
          version: "1.0.0",
          target: "native",
          native_renderer: "html",
          entry_url: "",
        },
        code: { language: "html", content: "<p>hello figure</p>" },
      })}
    />,
  );

  const iframe = screen.getByTitle("HTML visualization");
  expect(iframe).toBeInTheDocument();
  expect(iframe.getAttribute("srcdoc")).toContain("<p>hello figure</p>");
  expect(
    screen.queryByRole("button", { name: "Fullscreen" }),
  ).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Open in new tab" }));
  expect(openSpy).toHaveBeenCalledWith(
    expect.stringContaining("blob:"),
    "_blank",
    "noopener,noreferrer",
  );
});

it("grows the html iframe via bridge height reports and ignores foreign sources", () => {
  const { container } = render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "html",
        renderer: {
          id: "html",
          version: "1.0.0",
          target: "native",
          native_renderer: "html",
          entry_url: "",
        },
        code: { language: "html", content: "<p>hi</p>" },
      })}
    />,
  );
  const iframe = screen.getByTitle("HTML visualization") as HTMLIFrameElement;

  // A message from another window must not resize the iframe.
  fireEvent(
    window,
    new MessageEvent("message", {
      source: window,
      data: { type: "dt:visualize-height", height: 4000 },
    }),
  );
  expect(iframe.style.height).not.toBe("2400px");

  fireEvent(
    window,
    new MessageEvent("message", {
      source: iframe.contentWindow,
      data: { type: "dt:visualize-height", height: 4000 },
    }),
  );
  expect(iframe.style.height).toBe("2400px");

  const promptEvents: string[] = [];
  const onPrompt = (event: Event) => {
    promptEvents.push((event as CustomEvent<string>).detail);
  };
  window.addEventListener("dt:visualize-prompt", onPrompt);
  fireEvent(
    window,
    new MessageEvent("message", {
      source: iframe.contentWindow,
      data: { type: "dt:visualize-prompt", text: "explain this figure" },
    }),
  );
  window.removeEventListener("dt:visualize-prompt", onPrompt);
  expect(promptEvents).toEqual(["explain this figure"]);
  expect(container.querySelector("iframe")).not.toBeNull();
});

it("embeds a plugin renderer iframe when an entry url is present", () => {
  render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "desmos",
        renderer: {
          id: "desmos-plugin",
          version: "1.0.0",
          target: "iframe",
          native_renderer: "",
          entry_url: "https://plugins.example/render",
        },
        presentation: {
          title: "Sorting demo",
          description: "",
          alt_text: "",
          aspect_ratio: "",
        },
      })}
    />,
  );

  const iframe = screen.getByTitle("Sorting demo") as HTMLIFrameElement;
  expect(iframe).toBeInTheDocument();
  expect(iframe.getAttribute("src")).toBe("https://plugins.example/render");
  expect(
    screen.queryByRole("button", { name: "Fullscreen" }),
  ).not.toBeInTheDocument();
});

it("shows a fallback when the plugin renderer entry url is missing", () => {
  render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "desmos",
        renderer: {
          id: "desmos-plugin",
          version: "1.0.0",
          target: "iframe",
          native_renderer: "",
          entry_url: "",
        },
      })}
    />,
  );
  expect(
    screen.getByText("Visualizer renderer is unavailable"),
  ).toBeInTheDocument();
});

it("delegates the geogebra renderer to the geogebra component", async () => {
  render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "geogebra",
        renderer: {
          id: "geogebra",
          version: "1.0.0",
          target: "native",
          native_renderer: "geogebra",
          entry_url: "",
        },
        presentation: {
          title: "Parabola",
          description: "",
          alt_text: "",
          aspect_ratio: "",
        },
      })}
    />,
  );
  expect(await screen.findByTestId("geogebra-stub")).toBeInTheDocument();
  expect(screen.getByText("Parabola")).toBeInTheDocument();
});

it("renders an unknown native renderer as an explicit error", () => {
  render(
    <VisualizationViewer
      result={canvasResult({
        render_type: "particle3d",
        renderer: {
          id: "particle3d",
          version: "1.0.0",
          target: "native",
          native_renderer: "",
          entry_url: "",
        },
      })}
    />,
  );
  expect(
    screen.getByText("No native renderer is registered for particle3d."),
  ).toBeInTheDocument();
});

it("delegates manim results to the math animator viewer", async () => {
  render(<VisualizationViewer result={manimResult} />);
  expect(await screen.findByTestId("math-animator-stub")).toBeInTheDocument();
  expect(screen.getByText("video")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Show code" }),
  ).not.toBeInTheDocument();
});
