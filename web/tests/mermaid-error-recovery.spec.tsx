import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Mermaid } from "@/components/Mermaid";

const renderer = vi.hoisted(() => ({
  render: vi.fn(),
  initialize: vi.fn(),
  t: (value: string) => value,
}));
vi.mock("mermaid", () => ({ default: renderer }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: renderer.t }) }));

describe("Mermaid rendering recovery", () => {
  it("renders a corrected chart after a renderer error", async () => {
    const correctedChart = "flowchart TD; A-->B";
    renderer.render.mockReset().mockImplementation(async (_id: string, chart: string) => {
      if (chart !== correctedChart) throw new Error("Parse error");
      return { svg: '<svg aria-label="corrected diagram"></svg>' };
    });
    const { rerender } = render(<Mermaid chart="flowchart TD; A[" />);
    await screen.findByText("Diagram rendering error", {}, { timeout: 2500 });
    rerender(<Mermaid chart={correctedChart} />);
    expect(await screen.findByLabelText("corrected diagram", {}, { timeout: 2500 }))
      .toBeInTheDocument();
    expect(renderer.render).toHaveBeenCalledWith(expect.any(String), correctedChart);
    expect(screen.queryByText("Diagram rendering error")).not.toBeInTheDocument();
  });
});
