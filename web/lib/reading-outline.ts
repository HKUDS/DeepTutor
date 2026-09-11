import type { OutlineRow } from "@/lib/reading-api";

export interface OutlineNode {
  row: OutlineRow;
  children: OutlineNode[];
}

export interface ReaderHeading {
  id: string;
  title: string;
  level: number;
  /** EPUB spine locator containing this heading. */
  locator?: number;
  /** EPUB spine href used to navigate across chapter boundaries. */
  sourceHref?: string;
}

export interface ReaderDisplayLine {
  /** The original source line, including Markdown heading markers. */
  text: string;
  heading: ReaderHeading | null;
  /** Inside (or is a boundary of) a fenced code block — render literally. */
  fence: boolean;
}

export function headingAnchor(locator: number, index: number): string {
  return `dt-reader-heading-${locator}-${index + 1}`;
}

const HEADING_PATTERN = /^(#{1,6})\s+(.+?)\s*#*$/;

export function readerHeadingLine(line: string): ReaderHeading | null {
  const match = HEADING_PATTERN.exec(line.trim());
  if (!match) return null;
  const title = match[2].replace(/\s+#+$/, "").trim();
  if (!title) return null;
  return { id: "", title, level: match[1].length };
}

export interface EpubHeadingElement {
  id?: string | null;
  tagName: string;
  textContent: string | null;
}

/** Extract EPUB headings while preserving publisher-provided anchors. */
export function extractEpubHeadings(
  elements: EpubHeadingElement[],
  locator: number,
  sourceHref?: string,
): ReaderHeading[] {
  const headings: ReaderHeading[] = [];
  for (const element of elements) {
    const match = /^h([1-6])$/i.exec(element.tagName);
    if (!match) continue;
    const title = (element.textContent ?? "").replace(/\s+/g, " ").trim();
    if (!title) continue;
    headings.push({
      id: element.id?.trim() || headingAnchor(locator, headings.length),
      title,
      level: Number(match[1]),
      locator,
      sourceHref,
    });
  }
  return headings;
}

/**
 * Attach outline entries to source lines without changing a single character.
 *
 * Recogito's TextPosition selectors resolve against ``article.textContent``.
 * Keeping the Markdown markers and the original newline text nodes here makes
 * that DOM text exactly equal to the text used when an annotation was saved.
 */
export function readerLinesWithHeadings(
  text: string,
  headings: ReaderHeading[],
): ReaderDisplayLine[] {
  let fence: string | null = null;
  let headingIndex = 0;
  return text.split("\n").map((line) => {
    const fenceMatch = /^\s*(`{3,}|~{3,})/.exec(line);
    if (fenceMatch) {
      // The fence delimiter line itself is reported as `fence: true` too, so
      // the renderer never runs Markdown formatting over a stray ``` marker.
      if (!fence) fence = fenceMatch[1];
      else if (line.trim().startsWith(fence)) fence = null;
      return { text: line, heading: null, fence: true };
    }
    if (fence) return { text: line, heading: null, fence: true };

    const parsed = readerHeadingLine(line);
    if (!parsed) return { text: line, heading: null, fence: false };
    const expected = headings[headingIndex++];
    if (
      !expected ||
      expected.title !== parsed.title ||
      expected.level !== parsed.level
    ) {
      return { text: line, heading: null, fence: false };
    }
    return { text: line, heading: expected, fence: false };
  });
}

/** Extract Markdown headings while ignoring fenced code blocks. */
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
      const heading = readerHeadingLine(line);
      if (heading) {
        headings.push({
          ...heading,
          id: headingAnchor(locator, headings.length),
        });
      }
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
  return nodes.map(visit).filter((row): row is OutlineNode => row !== null);
}

export function buildOutlineTree(rows: OutlineRow[]): OutlineNode[] {
  const roots: OutlineNode[] = [];
  const stack: { level: number; node: OutlineNode }[] = [];

  rows.forEach((row) => {
    let level = Math.max(1, row.level);
    if (!stack.length) level = 1;
    else level = Math.min(level, stack[stack.length - 1].level + 1);

    const node: OutlineNode = { row, children: [] };
    while (stack.length && stack[stack.length - 1].level >= level) stack.pop();
    if (stack.length) stack[stack.length - 1].node.children.push(node);
    else roots.push(node);
    stack.push({ level, node });
  });

  return roots;
}
