import { describe, expect, it } from "vitest";

import {
  createCodeCell,
  createGeogebraCell,
  createMarkdownCell,
  parseNotebookMarkdown,
  serializeNotebookMarkdown,
} from "@/lib/notebook-cells";

describe("notebook cells", () => {
  it("round-trips notes and fenced code without changing cells", () => {
    const cells = [
      createMarkdownCell("# Title\n\nSome $x^2$ math."),
      createCodeCell("print('hi')\nx = 1", "python"),
      createMarkdownCell("After."),
    ];
    const markdown = serializeNotebookMarkdown(cells);
    const parsed = parseNotebookMarkdown(markdown);

    expect(parsed.map((c) => c.kind)).toEqual(["markdown", "code", "markdown"]);
    expect(parsed[1].source).toBe("print('hi')\nx = 1");
    expect(parsed[1].language).toBe("python");
    expect(parsed[0].source).toContain("$x^2$");
  });

  it("reads a language from the fence and normalises aliases", () => {
    const parsed = parseNotebookMarkdown("```py\nprint(1)\n```");
    expect(parsed).toHaveLength(1);
    expect(parsed[0].kind).toBe("code");
    expect(parsed[0].language).toBe("python");
  });

  it("falls back to a fresh notebook for empty input", () => {
    const parsed = parseNotebookMarkdown("");
    expect(parsed.length).toBeGreaterThan(0);
    expect(parsed.some((c) => c.kind === "code")).toBe(true);
  });

  it("keeps a GeoGebra board cell across a round-trip", () => {
    const cells = [
      createMarkdownCell("Figure:"),
      createGeogebraCell("A=(1,2)\nB=(3,4)\nSegment(A,B)"),
    ];
    const markdown = serializeNotebookMarkdown(cells);
    expect(markdown).toContain("```geogebra");

    const parsed = parseNotebookMarkdown(markdown);
    expect(parsed.map((c) => c.kind)).toEqual(["markdown", "geogebra"]);
    expect(parsed[1].source).toContain("Segment(A,B)");
  });
});
