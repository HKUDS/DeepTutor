import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Mermaid } from "@/components/Mermaid";

const renderer = vi.hoisted(() => ({ render: vi.fn(), initialize: vi.fn() }));
vi.mock("mermaid", () => ({ default: renderer }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (value: string) => value }) }));

describe("Mermaid rendering recovery", () => {
  it("renders a corrected chart after a renderer error", async () => {
    renderer.render.mockReset()
      .mockRejectedValueOnce(new Error("Parse error"))
      .mockResolvedValueOnce({ svg: '<svg aria-label="corrected diagram"></svg>' });
    const { rerender } = render(<Mermaid chart="flowchart TD; A[" />);
    await screen.findByText("Diagram rendering error", {}, { timeout: 2500 });
    rerender(<Mermaid chart="flowchart TD; A-->B" />);
    await waitFor(() => expect(renderer.render).toHaveBeenCalledTimes(2), { timeout: 2500 });
    expect(screen.getByLabelText("corrected diagram")).toBeInTheDocument();
    expect(screen.queryByText("Diagram rendering error")).not.toBeInTheDocument();
  });
});
