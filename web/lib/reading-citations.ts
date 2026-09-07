import { toolResultMetadata } from "@/lib/tool-event";
/**
 * Locator citations in assistant prose: `[p.12]`, `[p.12,17]`, `[p.12-14]`.
 *
 * The model is asked for that one form regardless of what the document's units
 * are called, so there is a single pattern to parse and the UI decides whether
 * to *show* "page 12" or "chapter 12" from the material's own unit word.
 *
 * ## Why rewrite to a link instead of rendering a component
 *
 * Citations become ordinary Markdown links (`[p.12](#dt-locator-12)`), which the
 * existing renderer turns into ordinary anchors; the reader then catches clicks
 * with one delegated listener. That keeps this feature out of the shared
 * Markdown renderer entirely — no new props, no new branches in code that every
 * other chat surface also runs.
 *
 * ## Why code spans are excluded first
 *
 * A bracketed token inside code is code, not a citation. DeepTutor has already
 * shipped the bug where `[0]` in a snippet was linkified into a citation anchor
 * (issue #468), so this parser masks fenced blocks and inline code *before*
 * matching rather than hoping the pattern is narrow enough.
 */

/** One parsed citation and the locators it points at. */
export interface LocatorCitation {
  /** Exact source text, e.g. `"[p.12,17]"`. */
  raw: string;
  /** Locators in ascending order, de-duplicated. */
  locators: number[];
  /** Character offsets of `raw` within the input. */
  start: number;
  end: number;
}

/** Anchor prefix the reader listens for. */
export const LOCATOR_HREF_PREFIX = "#dt-locator-";
const MATERIAL_LOCATOR_HREF_PREFIX = "#dt-material-";
const READING_EVIDENCE_TOOLS = new Set([
  "search_material",
  "read_material",
  "reader_goto",
]);

export interface ReadingCitationTarget {
  materialId?: string;
  materialRevision?: number;
  locator: number;
}

interface ReadingEvidenceEvent {
  type?: string;
  metadata?: unknown;
}

/** Largest locator span a single `[p.a-b]` may expand to. */
const MAX_RANGE_SPAN = 40;

// `[p.` then digits with , - – separators, then `]` — but not when followed by
// `(`, which would mean it is already a Markdown link's label.
const CITATION = /\[p\.\s*(\d[\d\s,–—-]*)\]/gi;

/**
 * Character ranges occupied by fenced blocks or inline code.
 *
 * Fences are matched first and their interiors skipped wholesale, so a stray
 * backtick inside a fence cannot desynchronise the inline-code scan.
 */
export function codeRanges(text: string): Array<[number, number]> {
  const ranges: Array<[number, number]> = [];
  const fence =
    /(^|\n)[ \t]*(`{3,}|~{3,})[^\n]*\n?[\s\S]*?(?:\n[ \t]*\2[ \t]*(?=\n|$)|$)/g;
  let match: RegExpExecArray | null;
  while ((match = fence.exec(text)) !== null) {
    ranges.push([match.index, match.index + match[0].length]);
  }

  const inFence = (index: number) =>
    ranges.some(([from, to]) => index >= from && index < to);

  // Inline code: the shortest run of backticks that closes with the same count.
  const inline = /(`+)(?:[^`]|(?!\1)`)*?\1/g;
  while ((match = inline.exec(text)) !== null) {
    if (!inFence(match.index)) {
      ranges.push([match.index, match.index + match[0].length]);
    }
  }
  return ranges.sort((a, b) => a[0] - b[0]);
}

function parseLocatorList(body: string): number[] {
  const found = new Set<number>();
  for (const chunk of body.split(",")) {
    const piece = chunk.trim();
    if (!piece) continue;
    const range = /^(\d+)\s*[–—-]\s*(\d+)$/.exec(piece);
    if (range) {
      let from = Number(range[1]);
      let to = Number(range[2]);
      if (from > to) [from, to] = [to, from];
      for (let n = from; n <= Math.min(to, from + MAX_RANGE_SPAN); n += 1) {
        if (n >= 1) found.add(n);
      }
      continue;
    }
    const single = /^(\d+)$/.exec(piece);
    if (single) {
      const n = Number(single[1]);
      if (n >= 1) found.add(n);
    }
  }
  return [...found].sort((a, b) => a - b);
}

/**
 * Words a model uses when it names a location in prose, per unit kind.
 *
 * Matched case-insensitively and in both scripts, because the answer's language
 * follows the user's, not the document's.
 */
const SPELLED_OUT_LOCATION = new RegExp(
  "(?:" +
    // English: "page 3", "on pages 3", "chapter 3", "slide 3", "section 3"
    "(?:pages?|chapters?|slides?|sections?)\\s*(\\d+)" +
    "|" +
    // Chinese: "第 3 页", "第3章", "第 3 节", "第3张幻灯片"
    "第\\s*(\\d+)\\s*(?:页|章|节|张幻灯片|张)" +
    ")",
  "gi",
);

/** How far back from a citation we look for the phrase it duplicates. */
const ABSORB_WINDOW = 90;

interface Absorption {
  /** Character range of the prose phrase to turn into the link. */
  start: number;
  end: number;
  /** The phrase itself, kept verbatim so the sentence still reads naturally. */
  label: string;
}

/**
 * Find a spelled-out location just before *citation* that names the same unit.
 *
 * Models answering "where is it?" naturally write the location into the
 * sentence — "is located on page 3 of the document [p.3]" — leaving the marker
 * as a second, redundant copy. Rather than fight that with prompt rules (which
 * a fast model ignores) or delete the words (which breaks the sentence), the
 * phrase itself becomes the link and the marker is dropped. One link, in the
 * place the reader is already looking.
 */
function findAbsorbablePhrase(
  text: string,
  citation: LocatorCitation,
  skip: Array<[number, number]>,
): Absorption | null {
  // Only for single-locator citations: "[p.12,17]" has no one phrase to absorb.
  if (citation.locators.length !== 1) return null;
  const locator = citation.locators[0];

  const from = Math.max(0, citation.start - ABSORB_WINDOW);
  const window = text.slice(from, citation.start);
  // Never reach across a sentence boundary or a link that is already there.
  const lastBreak = Math.max(
    window.lastIndexOf("."),
    window.lastIndexOf("。"),
    window.lastIndexOf("\n"),
    window.lastIndexOf(")"),
    window.lastIndexOf("]"),
  );
  const searchFrom = from + (lastBreak >= 0 ? lastBreak + 1 : 0);
  const searchable = text.slice(searchFrom, citation.start);

  let best: Absorption | null = null;
  SPELLED_OUT_LOCATION.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = SPELLED_OUT_LOCATION.exec(searchable)) !== null) {
    const value = Number(match[1] ?? match[2]);
    if (value !== locator) continue;
    const start = searchFrom + match.index;
    const end = start + match[0].length;
    if (skip.some(([lo, hi]) => start < hi && end > lo)) continue;
    // Keep the LAST match: it is the one adjacent to the citation.
    best = { start, end, label: match[0] };
  }
  return best;
}

/** Every citation in *text*, skipping code spans. */
export function findLocatorCitations(text: string): LocatorCitation[] {
  if (!text) return [];
  const skip = codeRanges(text);
  const masked = (index: number) =>
    skip.some(([from, to]) => index >= from && index < to);

  const out: LocatorCitation[] = [];
  CITATION.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CITATION.exec(text)) !== null) {
    const start = match.index;
    if (masked(start)) continue;
    // Already a Markdown link label — leave it alone.
    if (text[start + match[0].length] === "(") continue;
    const locators = parseLocatorList(match[1]);
    if (!locators.length) continue;
    out.push({
      raw: match[0],
      locators,
      start,
      end: start + match[0].length,
    });
  }
  return out;
}

/**
 * Rewrite citations into Markdown links the reader can intercept.
 *
 * `maxLocator` (the material's unit count) drops references the document cannot
 * have: a link to page 900 of a 12-page PDF would be a dead end, and leaving it
 * as plain text is a more honest signal than a link that goes nowhere.
 */
export function linkifyLocatorCitations(
  text: string,
  options: {
    maxLocator?: number;
    materialId?: string;
    materialRevision?: number;
    allowedLocators?: Iterable<number>;
  } = {},
): string {
  const citations = findLocatorCitations(text);
  if (!citations.length) return text;
  const { maxLocator, materialId, materialRevision } = options;
  const allowed = options.allowedLocators
    ? new Set(options.allowedLocators)
    : null;

  const skip = codeRanges(text);
  let out = "";
  let cursor = 0;
  for (const citation of citations) {
    if (allowed && citation.locators.some((locator) => !allowed.has(locator))) {
      out += text.slice(cursor, citation.end);
      cursor = citation.end;
      continue;
    }
    const locators =
      typeof maxLocator === "number" && maxLocator > 0
        ? citation.locators.filter((n) => n <= maxLocator)
        : citation.locators;
    if (!locators.length) {
      out += text.slice(cursor, citation.end);
      cursor = citation.end;
      continue;
    }

    const revisionAddress =
      Number.isSafeInteger(materialRevision) && Number(materialRevision) >= 1
        ? `-revision-${materialRevision}`
        : "";
    const href = materialId
      ? `${MATERIAL_LOCATOR_HREF_PREFIX}${encodeURIComponent(materialId)}${revisionAddress}-locator-${locators[0]}`
      : `${LOCATOR_HREF_PREFIX}${locators[0]}`;
    const absorbed =
      locators.length === citation.locators.length
        ? findAbsorbablePhrase(text, citation, skip)
        : null;

    if (absorbed && absorbed.start >= cursor) {
      // Link the phrase, then skip the marker and the whitespace that led to it
      // so the sentence closes cleanly: "…located on [page 3](…) of the
      // document." rather than "…of the document ."
      out += text.slice(cursor, absorbed.start);
      out += `[${absorbed.label}](${href})`;
      const between = text.slice(absorbed.end, citation.start);
      out += between.replace(/\s+$/, "");
      cursor = citation.end;
      continue;
    }

    out += text.slice(cursor, citation.start);
    out += `[p.${locators.join(",")}](${href})`;
    cursor = citation.end;
  }
  return out + text.slice(cursor);
}

/** Locator encoded in an anchor href, or null when it is a different link. */
export function locatorFromHref(
  href: string | null | undefined,
): number | null {
  return citationTargetFromHref(href)?.locator ?? null;
}

/** Material-aware reader address, with support for legacy locator-only links. */
export function citationTargetFromHref(
  href: string | null | undefined,
): ReadingCitationTarget | null {
  if (!href) return null;
  if (href.startsWith(LOCATOR_HREF_PREFIX)) {
    const locator = Number(href.slice(LOCATOR_HREF_PREFIX.length));
    return Number.isInteger(locator) && locator >= 1 ? { locator } : null;
  }
  if (!href.startsWith(MATERIAL_LOCATOR_HREF_PREFIX)) return null;
  const match =
    /^#dt-material-([0-9a-f]{8,64})(?:-revision-(\d+))?-locator-(\d+)$/i.exec(
      href,
    );
  if (!match) return null;
  const materialRevision = match[2] ? Number(match[2]) : undefined;
  const locator = Number(match[3]);
  const materialId = match[1];
  if (!Number.isSafeInteger(locator) || locator < 1) return null;
  if (
    materialRevision !== undefined &&
    (!Number.isSafeInteger(materialRevision) || materialRevision < 1)
  ) {
    return null;
  }
  return {
    materialId: materialId.toLowerCase(),
    ...(materialRevision !== undefined ? { materialRevision } : {}),
    locator,
  };
}

/** Locators grounded by successful reading-tool results for one turn. */
export function verifiedReadingLocators(
  events: ReadingEvidenceEvent[] | null | undefined,
  materialId: string | null | undefined,
  materialRevision?: number | null,
): Set<number> {
  const verified = new Set<number>();
  if (!materialId) return verified;
  const expected = materialId.toLowerCase();
  for (const event of events ?? []) {
    if (event.type !== "tool_result" || !event.metadata) continue;
    const outer = event.metadata as Record<string, unknown>;
    const tool = String(outer.tool ?? outer.tool_name ?? "");
    if (!READING_EVIDENCE_TOOLS.has(tool)) {
      continue;
    }
    const metadata = toolResultMetadata(outer);
    if (!metadata) continue;
    if (String(metadata.material_id ?? "").toLowerCase() !== expected) continue;
    if (materialRevision) {
      const evidenceRevision = Number(metadata.material_revision);
      if (evidenceRevision !== materialRevision) continue;
    }
    const add = (value: unknown) => {
      const locator = Number(value);
      if (Number.isInteger(locator) && locator >= 1) verified.add(locator);
    };
    if (Array.isArray(metadata.locators)) metadata.locators.forEach(add);
    if (Array.isArray(metadata.hits)) {
      metadata.hits.forEach((hit) => {
        if (hit && typeof hit === "object") {
          add((hit as Record<string, unknown>).locator);
        }
      });
    }
    add(metadata.locator);
    add(metadata.found_locator);
  }
  return verified;
}

/** Human label for a locator, using the material's own unit word. */
export function locatorLabel(unit: string, locator: number): string {
  const word = unit || "page";
  return `${word} ${locator}`;
}
