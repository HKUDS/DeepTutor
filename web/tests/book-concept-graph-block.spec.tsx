import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import ConceptGraphBlock from "@/app/(workspace)/learning/books/components/blocks/ConceptGraphBlock";
import type { Block } from "@/lib/book-types";
import { initI18n } from "@/i18n/init";

vi.mock("@/components/common/MarkdownRenderer", () => ({
  default: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

initI18n("en");

const block = {
  id: "blk_graph",
  type: "concept_graph",
  status: "ready",
  title: "",
  params: {},
  payload: {
    graph: {
      nodes: [
        {
          id: "limits",
          label: "Limits and Continuity",
          chapter_id: "",
          description: "Limits set up continuity.",
          weight: 1,
        },
        {
          id: "derivatives",
          label: "Differentiation",
          chapter_id: "",
          description: "Derivatives measure change.",
          weight: 1,
        },
      ],
      edges: [
        {
          src: "limits",
          dst: "derivatives",
          relation: "depends_on",
          rationale: "",
        },
      ],
    },
  },
  source_anchors: [],
  metadata: {},
  error: "",
  created_at: 0,
  updated_at: 0,
} as unknown as Block;

it("keeps the mermaid graph and reveals a node explanation on click", () => {
  render(<ConceptGraphBlock block={block} />);

  // The static mermaid visual is still rendered from the structured graph.
  expect(screen.getAllByTestId("markdown")[0].textContent).toContain("graph TD");

  fireEvent.click(screen.getByRole("button", { name: "Limits and Continuity" }));
  expect(screen.getByText("Limits set up continuity.")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Differentiation" }));
  expect(screen.getByText("Derivatives measure change.")).toBeInTheDocument();
  expect(screen.queryByText("Limits set up continuity.")).not.toBeInTheDocument();

  // Clicking the active node parks the explanation again.
  fireEvent.click(screen.getByRole("button", { name: "Differentiation" }));
  expect(screen.queryByText("Derivatives measure change.")).not.toBeInTheDocument();
});