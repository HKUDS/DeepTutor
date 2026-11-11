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
  /** Which handle the line leaves from and lands on ("right" / "left"). */
  sourceHandle?: string;
  targetHandle?: string;
}

/** A short label with a colour, shown on a cell's card. */
export interface NotebookTag {
  label: string;
  color: string;
}

export interface NotebookGraph {
  positions: Record<string, NotebookGraphPoint>;
  edges: NotebookGraphEdge[];
  /** Per-cell tag, keyed by cell id. */
  tags: Record<string, NotebookTag>;
}

/** Colours a tag can take (kept in sync with the picker). */
export const NOTEBOOK_TAG_COLORS = [
  "#ef4444",
  "#f59e0b",
  "#eab308",
  "#22c55e",
  "#14b8a6",
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#64748b",
] as const;

export function emptyNotebookGraph(): NotebookGraph {
  return { positions: {}, edges: [], tags: {} };
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

function isTagMap(value: unknown): value is Record<string, NotebookTag> {
  if (!value || typeof value !== "object") return false;
  return Object.values(value).every(
    (tag) =>
      Boolean(tag) &&
      typeof (tag as NotebookTag).label === "string" &&
      typeof (tag as NotebookTag).color === "string",
  );
}

function isNameMap(value: unknown): value is Record<string, string> {
  if (!value || typeof value !== "object") return false;
  return Object.values(value).every((name) => typeof name === "string");
}

/**
 * Pull the hidden `dt-graph` block out of the page, returning the remaining
 * Markdown (the cells) and the graph. A malformed block is dropped rather than
 * breaking the notebook.
 */
export function splitNotebookGraph(markdown: string): {
  body: string;
  graph: NotebookGraph;
  /** Cell ids in order, so links survive a reload (ids are otherwise fresh). */
  cellIds: string[];
  /** Learner-given cell names, keyed by cell id. */
  names: Record<string, string>;
} {
  const text = String(markdown ?? "");
  const lines = text.split("\n");
  const bodyLines: string[] = [];
  let graph = emptyNotebookGraph();
  let cellIds: string[] = [];
  let names: Record<string, string> = {};
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
        graph = {
          positions: parsed.positions,
          edges: parsed.edges,
          tags: isTagMap((parsed as { tags?: unknown }).tags)
            ? (parsed as { tags: Record<string, NotebookTag> }).tags
            : {},
        };
        const rawCells = (parsed as { cells?: unknown }).cells;
        if (Array.isArray(rawCells)) {
          cellIds = rawCells.filter(
            (id): id is string => typeof id === "string",
          );
        }
        const rawNames = (parsed as { names?: unknown }).names;
        names = isNameMap(rawNames) ? rawNames : {};
        found = true;
      }
    } catch {
      // A corrupt block is ignored; the cells still load.
    }
  }

  return { body: bodyLines.join("\n"), graph, cellIds, names };
}

/**
 * Write the graph back as a hidden block, after the cells. Nothing is written
 * when both the graph and the cell names are empty, so a notebook that never
 * used the graph view stays plain Markdown.
 */
export function appendNotebookGraph(
  markdown: string,
  graph: NotebookGraph,
  cellIds: string[],
  names: Record<string, string> = {},
): string {
  const known = new Set(cellIds);
  const positions = Object.fromEntries(
    Object.entries(graph.positions).filter(([id]) => known.has(id)),
  );
  const edges = graph.edges.filter(
    (edge) => known.has(edge.from) && known.has(edge.to),
  );
  const tags = Object.fromEntries(
    Object.entries(graph.tags).filter(([id]) => known.has(id)),
  );
  const cellNames = Object.fromEntries(
    Object.entries(names)
      .filter(([id, name]) => known.has(id) && name.trim())
      .map(([id, name]) => [id, name.trim()]),
  );
  if (
    !edges.length &&
    !Object.keys(positions).length &&
    !Object.keys(tags).length &&
    !Object.keys(cellNames).length
  ) {
    return markdown;
  }

  const payload = JSON.stringify({
    cells: cellIds,
    positions,
    edges,
    tags,
    names: cellNames,
  });
  const block = `\`\`\`dt-graph\n${payload}\n\`\`\``;
  const base = String(markdown ?? "").replace(/\s+$/, "");
  return `${base ? `${base}\n\n` : ""}${block}\n`;
}
