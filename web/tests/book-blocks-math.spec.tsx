import { fireEvent, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CalloutBlock from "@/app/(workspace)/learning/books/components/blocks/CalloutBlock";
import FlashCardsBlock from "@/app/(workspace)/learning/books/components/blocks/FlashCardsBlock";
import SectionBlock from "@/app/(workspace)/learning/books/components/blocks/SectionBlock";
import type { Block } from "@/lib/book-types";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

function block(type: string, payload: Record<string, unknown>): Block {
  return { id: "blk-1", type, payload } as unknown as Block;
}

async function expectMath(container: HTMLElement, count: number) {
  await waitFor(() => expect(container.querySelectorAll(".katex")).toHaveLength(count));
  expect(container.textContent).not.toContain("$");
}

describe("book blocks render math", () => {
  it("in a callout body", async () => {
    const { container } = render(
      <CalloutBlock block={block("callout", { variant: "key_idea", body: "If $q > 1$ then $q^n \\to \\infty$." })} />,
    );
    await expectMath(container, 2);
  });

  it("in a section's key takeaway", async () => {
    const { container } = render(
      <SectionBlock block={block("section", { key_takeaway: "Divide by $n^k$." })} />,
    );
    await expectMath(container, 1);
  });

  it("on both sides of a flash card and in its hint", async () => {
    const { container, getAllByRole } = render(
      <FlashCardsBlock
        block={block("flash_cards", {
          cards: [{ front: "$\\lim \\frac{1}{n}$?", back: "$0$", hint: "Compare with $n$." }],
        })}
      />,
    );
    await expectMath(container, 2);
    fireEvent.click(getAllByRole("button")[0]);
    await expectMath(container, 1);
  });
});
