import type { OutlineRow } from "@/lib/reading-api";

export interface OutlineNode {
  row: OutlineRow;
  children: OutlineNode[];
}

export interface ReaderHeading {
  id: string;
  title: string;
  level: number;
}

export function headingAnchor(locator: number, index: number): string {
  return `dt-reader-heading-${locator}-${index + 1}`;
}

function markdownHeading(
  line: string,
  locator: number,
  index: number,
): ReaderHeading | null {
  const match = /^(#{1,6})\s+(.+?)\s*#*$/.exec(line.trim());
  if (!match) return null;
  const title = match[2].replace(/\s+#+$/, "").trim();
  if (!title) return null;
  return {
    id: headingAnchor(locator, index),
    title,
    level: match[1].length,
  };
}

/** Extract source headings while leaving fenced code and translation blocks alone. */
export function extractReaderHeadings(
  sources: Array<string | undefined | null>,
  locator: number,
): ReaderHeading[] {
  const headings: ReaderHeading[] = [];
  for (const source of sources) {
    if (!source) continue;
    let fence: string | null = null;
    for (const line of source.split(/\r?\n/)) {
      const fenceMatch = /^\s*(`{3,}|~{3,})/.exec(line);
      if (fenceMatch) {
        if (!fence) fence = fenceMatch[1];
        else if (line.trim().startsWith(fence)) fence = null;
        continue;
      }
      if (fence) continue;
      const heading = markdownHeading(line, locator, headings.length);
      if (heading) headings.push(heading);
    }
  }
  return headings;
}

export function activeReaderHeading(
  headings: ReaderHeading[],
  getHeadingTop: (heading: ReaderHeading) => number | null,
): string | null {
  let active: string | null = null;
  for (const heading of headings) {
    const top = getHeadingTop(heading);
    if (top !== null && top <= 48) active = heading.id;
  }
  return active;
}

export function filterReaderHeadings(
  headings: ReaderHeading[],
  query: string,
): ReaderHeading[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return headings;
  return headings.filter((heading) =>
    heading.title.toLowerCase().includes(needle),
  );
}

export function filterOutlineNodes(
  nodes: OutlineNode[],
  query: string,
): OutlineNode[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return nodes;
  const visit = (node: OutlineNode): OutlineNode | null => {
    const children = node.children
      .map(visit)
      .filter((row): row is OutlineNode => row !== null);
    return node.row.title.toLowerCase().includes(needle) || children.length
      ? { row: node.row, children }
      : null;
  };
  return nodes
    .map(visit)
    .filter((row): row is OutlineNode => row !== null);
}

function recoverLevels(rows: OutlineRow[], sourcePaths?: string[]): number[] {
  if (rows.some((row) => row.level > 1)) {
    return rows.map((row) => Math.max(1, row.level));
  }

  // Legacy KB tutorials persisted every navigation node at level 1 even when
  // the source navigation had children. Their `kb_path` remains ordered and
  // retains Docusaurus's index/child convention (`section.md` followed by
  // `section/page.md`). New revisions use their original navigation levels and
  // never enter this compatibility branch.
  const paths =
    sourcePaths && sourcePaths.length === rows.length ? sourcePaths : undefined;
  if (!paths) return rows.map(() => 1);

  const pathIndexes = new Map(paths.map((path, index) => [path, index]));
  const levels: number[] = [];
  paths.forEach((path, index) => {
    const directory = path.split("/").slice(0, -1).join("/");
    const parentPath = directory ? `${directory}.md` : "";
    const parentIndex = parentPath ? pathIndexes.get(parentPath) : undefined;
    const parentLevel =
      parentIndex !== undefined && parentIndex < index
        ? levels[parentIndex]
        : undefined;
    levels.push(parentLevel ? parentLevel + 1 : 1);
  });
  return levels;
}

export function buildOutlineTree(
  rows: OutlineRow[],
  sourcePaths?: string[],
): OutlineNode[] {
  const roots: OutlineNode[] = [];
  const stack: { level: number; node: OutlineNode }[] = [];
  const levels = recoverLevels(rows, sourcePaths);

  rows.forEach((row, index) => {
    let level = levels[index] ?? 1;
    if (!stack.length) {
      level = 1;
    } else {
      level = Math.min(level, stack[stack.length - 1].level + 1);
    }

    const node: OutlineNode = { row, children: [] };
    while (stack.length && stack[stack.length - 1].level >= level) {
      stack.pop();
    }
    if (stack.length) {
      stack[stack.length - 1].node.children.push(node);
    } else {
      roots.push(node);
    }
    stack.push({ level, node });
  });

  return roots;
}
