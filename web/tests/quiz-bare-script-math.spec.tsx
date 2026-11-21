import { Suspense, lazy } from "react";
import { render, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import InlineMarkdown from "@/components/common/InlineMarkdown";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import RichInlineMarkdown from "@/components/common/RichInlineMarkdown";

vi.mock("next/dynamic", () => ({
  default: (loader: Parameters<typeof lazy>[0]) => lazy(loader),
}));

it("renders the reported bare scripts through the question's real KaTeX path", async () => {
  const view = render(
    <Suspense fallback={null}>
      <InlineMarkdown content="谐振频率 f_0 = 20 MHz，品质因数 Q_0 = 100，通频带 B_{0.707} = 0.4 MHz。" />
    </Suspense>,
  );
  await waitFor(() => expect(view.container.querySelectorAll(".katex")).toHaveLength(3));
  expect(view.container.querySelector(".katex-error")).toBeNull();
  expect(view.container.textContent).toContain("20 MHz");
  expect(Array.from(view.container.querySelectorAll('annotation[encoding="application/x-tex"]'))
    .map((node) => node.textContent)).toEqual(["f_0", "Q_0", "B_{0.707}"]);
});

it.each(["mastery", "quiz", "practice"] as const)(
  "renders both bare scripts in one %s choice",
  async (surface) => {
    const choice = "R'_L = 0.3125 kΩ，B_{0.707} = 0.4 MHz。 _提示_";
    const view = render(
      <Suspense fallback={null}>
        {surface === "mastery" ? (
          <InlineMarkdown content={choice} />
        ) : (
          <MarkdownRenderer content={choice} enableMath={surface === "quiz" ? true : undefined} />
        )}
      </Suspense>,
    );
    await waitFor(() => expect(view.container.querySelectorAll(".katex")).toHaveLength(2));
    expect(Array.from(view.container.querySelectorAll('annotation[encoding="application/x-tex"]'))
      .map((node) => node.textContent)).toEqual(["R'_L", "B_{0.707}"]);
    expect(view.container.querySelector(".katex-error")).toBeNull();
    expect(view.container.querySelector("em")?.textContent).toBe("提示");
  },
);

it("preserves code and link destinations even beside a recovered formula", async () => {
  const view = render(
    <RichInlineMarkdown content={"R'_L = 5 kΩ; `x_i^2`; user_id; a_1.txt\n\n[label][target]\n\n[target]: a_1"} />,
  );
  await waitFor(() => expect(view.container.querySelectorAll(".katex")).toHaveLength(1));
  expect(view.container.querySelector("code")?.textContent).toBe("x_i^2");
  expect(view.container.textContent).toContain("user_id; a_1.txt");
  expect(view.container.querySelector(".katex-error")).toBeNull();
});
