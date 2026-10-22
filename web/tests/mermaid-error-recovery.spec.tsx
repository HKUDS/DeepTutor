import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Mermaid } from "@/components/Mermaid";

const renderer = vi.hoisted(() => ({ render: vi.fn(), initialize: vi.fn() }));
vi.mock("mermaid", () => ({ default: renderer }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (value: string) => value }) }));

describe("Mermaid rendering recovery", () => {
  it("renders a corrected chart after a renderer error", async () => {
    renderer.render.mockReset().mockImplementation(async (_id, chart) => {
      if (chart.includes("[")) throw new Error("Parse error");
      return { svg: '<svg aria-label="corrected diagram"></svg>' };
    });
    const { rerender } = render(<Mermaid chart="flowchart TD; A[" />);
    await screen.findByText("Diagram rendering error", {}, { timeout: 2500 });
    rerender(<Mermaid chart="flowchart TD; A-->B" />);
    await screen.findByLabelText("corrected diagram", {}, { timeout: 2500 });
    expect(screen.getByLabelText("corrected diagram")).toBeInTheDocument();
    expect(screen.queryByText("Diagram rendering error")).not.toBeInTheDocument();
  });
});
