/**
 * Notebook graph — the mind-map layer over the notebook's cells.
 *
 * The notebook stays one Markdown page: fenced code is a code cell, prose is a
 * note. The graph adds two things Markdown has no place for — where each cell
 * sits and which cells are linked — and parks them in one hidden fenced block,
 * so the page is still plain Markdown the tutor can read and the layout
 * round-trips with the cells.
 *
 * A link's label is Markdown, which is what lets the line carry text, a
 * formula (`$...$`) or an image.
 */

export interface NotebookGraphPoint {
  x: number;
  y: number;
}

export interface NotebookGraphEdge {
  id: string;
  from: string;
  to: string;
  /** Markdown shown on the line: text, `$math$`, or an image. */
  label: string;
}

export interface NotebookGraph {
  positions: Record<string, NotebookGraphPoint>;
  edges: NotebookGraphEdge[];
}

export function emptyNotebookGraph(): NotebookGraph {
  return { positions: {}, edges: [] };
}

export function newNotebookEdgeId(): string {
  return `edge-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

const GRAPH_OPEN_RE = /^\s*(`{3,}|~{3,})\s*dt-graph\s*$/i;
const FENCE_CLOSE_RE = /^\s*(`{3,}|~{3,})\s*$/;

function isNotebookGraph(value: unknown): value is NotebookGraph {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<NotebookGraph>;
  return (
    typeof candidate.positions === "object" &&
    candidate.positions !== null &&
    Array.isArray(candidate.edges)
  );
}

/**
 * Pull the hidden `dt-graph` block out of the page, returning the remaining
 * Markdown (the cells) and the graph. A malformed block is dropped rather than
 * breaking the notebook.
 */
export function splitNotebookGraph(markdown: string): {
  body: string;
  graph: NotebookGraph;
} {
  const text = String(markdown ?? "");
  const lines = text.split("\n");
  const bodyLines: string[] = [];
  let graph = emptyNotebookGraph();
  let found = false;

  let i = 0;
  while (i < lines.length) {
    const open = GRAPH_OPEN_RE.exec(lines[i]);
    if (!open || found) {
      bodyLines.push(lines[i]);
      i += 1;
      continue;
    }
    const marker = open[1][0];
    const inner: string[] = [];
    i += 1;
    let closed = false;
    while (i < lines.length) {
      const close = FENCE_CLOSE_RE.exec(lines[i]);
      if (close && close[1][0] === marker) {
        closed = true;
        break;
      }
      inner.push(lines[i]);
      i += 1;
    }
    if (!closed) {
      // Unterminated: leave it as ordinary content rather than swallowing the
      // rest of the page.
      bodyLines.push(open[0]);
      bodyLines.push(...inner);
      continue;
    }
    i += 1; // consume the closing fence
    try {
      const parsed = JSON.parse(inner.join("\n"));
      if (isNotebookGraph(parsed)) {
        graph = { positions: parsed.positions, edges: parsed.edges };
        found = true;
      }
    } catch {
      // A corrupt block is ignored; the cells still load.
    }
  }

  return { body: bodyLines.join("\n"), graph };
}

/**
 * Write the graph back as a hidden block, after the cells. Nothing is written
 * when the graph is empty, so a notebook that never used the graph view stays
 * plain Markdown.
 */
export function appendNotebookGraph(
  markdown: string,
  graph: NotebookGraph,
  cellIds: string[],
): string {
  const known = new Set(cellIds);
  const positions = Object.fromEntries(
    Object.entries(graph.positions).filter(([id]) => known.has(id)),
  );
  const edges = graph.edges.filter(
    (edge) => known.has(edge.from) && known.has(edge.to),
  );
  if (!edges.length && !Object.keys(positions).length) return markdown;

  const payload = JSON.stringify({ positions, edges });
  const block = `\`\`\`dt-graph\n${payload}\n\`\`\``;
  const base = String(markdown ?? "").replace(/\s+$/, "");
  return `${base ? `${base}\n\n` : ""}${block}\n`;
}
