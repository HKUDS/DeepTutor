import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RichMarkdownRenderer from "@/components/common/RichMarkdownRenderer";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

describe("Rich Markdown reading direction", () => {
  it("marks prose blocks in a reply that also holds math", async () => {
    const { container } = render(
      <RichMarkdownRenderer
        content={"الجواب هو $x^2$\n\nHello\n\n$$y = 1$$"}
        variant="prose"
        enableMath
      />,
    );
    await waitFor(() => expect(container.querySelector(".katex")).not.toBeNull());
    const paragraphs = [...container.querySelectorAll("p")];
    expect(paragraphs.length).toBeGreaterThanOrEqual(2);
    for (const p of paragraphs) expect(p).toHaveAttribute("dir", "auto");
    // Formulas stay left-to-right: nothing above them forces a direction.
    for (const formula of container.querySelectorAll(".katex")) {
      expect(formula.closest("[dir]")).toHaveAttribute("dir", "ltr");
    }
    expect(container.querySelector(".md-renderer")).not.toHaveAttribute("dir");
  });
});
