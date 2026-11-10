import { describe, expect, it } from "vitest";

import {
  appendNotebookGraph,
  emptyNotebookGraph,
  splitNotebookGraph,
} from "@/lib/notebook-graph";

describe("notebook graph", () => {
  it("round-trips positions and links through the hidden block", () => {
    const cells = "# A\n\n```python\nx = 1\n```";
    const graph = {
      positions: { "cell-1": { x: 10, y: 20 } },
      edges: [
        { id: "e1", from: "cell-1", to: "cell-2", label: "if $a>0$ then …" },
      ],
      tags: { "cell-1": { label: "core", color: "#3b82f6" } },
    };
    const page = appendNotebookGraph(cells, graph, ["cell-1", "cell-2"]);
    expect(page).toContain("```dt-graph");

    const split = splitNotebookGraph(page);
    expect(split.body.trimEnd()).toBe(cells);
    expect(split.graph.edges).toHaveLength(1);
    expect(split.graph.edges[0].label).toBe("if $a>0$ then …");
    expect(split.graph.positions["cell-1"]).toEqual({ x: 10, y: 20 });
    expect(split.graph.tags["cell-1"]).toEqual({
      label: "core",
      color: "#3b82f6",
    });
    // The cell ids ride along, so the links can still find their cells.
    expect(split.cellIds).toEqual(["cell-1", "cell-2"]);
  });

  it("writes nothing when the graph is empty", () => {
    expect(appendNotebookGraph("# A", emptyNotebookGraph(), ["c"])).toBe("# A");
  });

  it("round-trips learner-given cell names", () => {
    const page = appendNotebookGraph(
      "note\n\n```python\nx = 1\n```",
      emptyNotebookGraph(),
      ["cell-a", "cell-b"],
      { "cell-a": "  Objectives  ", "cell-b": "   ", gone: "Dropped" },
    );
    const split = splitNotebookGraph(page);
    expect(split.names).toEqual({ "cell-a": "Objectives" });
  });

  it("keeps the body plain when only cell names are set", () => {
    const page = appendNotebookGraph(
      "# A",
      emptyNotebookGraph(),
      ["cell-a"],
      { "cell-a": "Intro" },
    );
    expect(page).toContain("```dt-graph");
    expect(splitNotebookGraph(page).body.trimEnd()).toBe("# A");
  });

  it("drops links and positions for cells that no longer exist", () => {
    const graph = {
      positions: { gone: { x: 1, y: 2 } },
      edges: [{ id: "e", from: "gone", to: "kept", label: "" }],
      tags: { gone: { label: "x", color: "#ef4444" } },
    };
    const split = splitNotebookGraph(appendNotebookGraph("body", graph, ["kept"]));
    expect(split.graph.edges).toHaveLength(0);
    expect(split.graph.positions).toEqual({});
    expect(split.graph.tags).toEqual({});
    expect(split.body.trimEnd()).toBe("body");
  });

  it("keeps a notebook readable when the block is corrupt", () => {
    const split = splitNotebookGraph("# A\n\n```dt-graph\n{not json\n```\n\ntail");
    expect(split.graph.edges).toEqual([]);
    expect(split.body).toContain("tail");
  });

  it("keeps cell ids stable across a reload so links survive", () => {
    const graph = {
      positions: {},
      edges: [{ id: "e1", from: "cell-a", to: "cell-b", label: "" }],
      tags: {},
    };
    const page = appendNotebookGraph(
      "note\n\n```python\nx = 1\n```",
      graph,
      ["cell-a", "cell-b"],
    );
    const split = splitNotebookGraph(page);
    expect(split.cellIds).toEqual(["cell-a", "cell-b"]);
    const ids = new Set(split.cellIds);
    expect(ids.has(split.graph.edges[0].from)).toBe(true);
    expect(ids.has(split.graph.edges[0].to)).toBe(true);
  });
});
