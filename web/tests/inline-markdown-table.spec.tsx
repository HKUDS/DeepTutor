import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import RichInlineMarkdown from "@/components/common/RichInlineMarkdown";

/**
 * A question stem can carry a GFM table. The inline renderer used to leave it
 * as raw pipe text; it now renders a real table inside the stem's typography.
 */
describe("RichInlineMarkdown", () => {
  it("renders a GFM table instead of raw pipes", () => {
    render(
      <RichInlineMarkdown
        content={"执行结果：\n\n| 工具 | 性质 |\n| --- | --- |\n| create_order | 写操作 |\n"}
      />,
    );

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("create_order")).toBeInTheDocument();
    expect(screen.getByText("写操作")).toBeInTheDocument();
    // The raw separator row must not survive as text.
    expect(screen.queryByText("---")).toBeNull();
  });
});
