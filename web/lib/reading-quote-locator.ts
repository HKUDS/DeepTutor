/**
 * Find a quote inside a rendered text layer, tolerantly.
 *
 * This is what turns "the model cited this sentence" into a highlight on the
 * page. It cannot be a plain `indexOf`: a pdf.js text layer splits a line into
 * many spans and preserves the PDF's own hard wraps, so the quote the model
 * copied out of the *extracted text* rarely matches the DOM text character for
 * character.
 *
 * The approach is to build a whitespace-collapsed projection of the layer's text
 * together with a map back to (segment, offset) positions, search in the
 * projection, then translate the hit back. Punctuation is softened the same way
 * the backend's matcher softens it, so curly quotes and dashes do not break a
 * match that a human would call identical.
 *
 * Pure over an array of segment strings, so the search is testable without a
 * DOM; the caller supplies the segments and maps the result back onto nodes.
 */

export interface QuotePosition {
  /** Index into the segments array. */
  segment: number;
  /** Character offset within that segment. */
  offset: number;
}

export interface QuoteRange {
  start: QuotePosition;
  end: QuotePosition;
  /** Which matching pass found it — callers may want to warn on "loose". */
  mode: "exact" | "collapsed" | "softened";
}

/** Punctuation that commonly differs between a PDF and a copied quote. */
const SOFT_CHARS = new Set([
  "‘",
  "’",
  "“",
  "”",
  "–",
  "—",
  "-",
  "_",
  "'",
  '"',
  "`",
  ",",
  "，",
  "、",
  ";",
  "；",
  ":",
  "：",
  ".",
  "。",
  "!",
  "！",
  "?",
  "？",
  "(",
  ")",
  "（",
  "）",
  "[",
  "]",
  "【",
  "】",
]);

interface Projection {
  text: string;
  /** For each character in `text`, where it came from. */
  origin: QuotePosition[];
}

interface ProjectOptions {
  soften: boolean;
  /**
   * Treat each segment boundary as whitespace.
   *
   * pdf.js splits a line into spans at visual breaks, and a span usually does
   * NOT end with a space — so `"…explicitly. Sinusoidal"` followed by
   * `"positional encodings…"` concatenates to `"Sinusoidalpositional"` and a
   * quote containing the space between them can never match. Inserting the
   * boundary space fixes Latin text; for CJK, which has no inter-word spaces,
   * the inserted space is what *breaks* a match. Neither choice is right for
   * both scripts, so both projections are tried.
   */
  joinWithSpace: boolean;
}

function project(segments: string[], options: ProjectOptions): Projection {
  const { soften, joinWithSpace } = options;
  let text = "";
  const origin: QuotePosition[] = [];
  let pendingSpace = false;

  for (let segment = 0; segment < segments.length; segment += 1) {
    if (joinWithSpace && segment > 0 && text.length > 0) pendingSpace = true;
    const value = segments[segment] ?? "";
    for (let offset = 0; offset < value.length; offset += 1) {
      const char = value[offset];
      if (/\s/.test(char)) {
        // Collapse any whitespace run to a single space, emitted lazily so a
        // trailing run never appears in the projection.
        if (text.length > 0) pendingSpace = true;
        continue;
      }
      if (soften && SOFT_CHARS.has(char)) continue;
      if (pendingSpace) {
        text += " ";
        origin.push({ segment, offset });
        pendingSpace = false;
      }
      text += char.toLowerCase();
      origin.push({ segment, offset });
    }
  }
  return { text, origin };
}

function projectQuote(quote: string, options: ProjectOptions): string {
  return project([quote], options).text;
}

function rangeFrom(
  projection: Projection,
  index: number,
  length: number,
  mode: QuoteRange["mode"],
): QuoteRange | null {
  const start = projection.origin[index];
  const lastChar = projection.origin[index + length - 1];
  if (!start || !lastChar) return null;
  return {
    start,
    // End offsets are exclusive, matching DOM Range semantics.
    end: { segment: lastChar.segment, offset: lastChar.offset + 1 },
    mode,
  };
}

/**
 * Locate *quote* within *segments*.
 *
 * Escalates through three passes and reports which one matched, so a caller can
 * treat a softened hit as lower-confidence. Returns null when even the softened
 * pass fails — better no highlight than a highlight on the wrong sentence.
 */
export function findQuoteRange(
  segments: string[],
  quote: string,
): QuoteRange | null {
  const needleRaw = (quote || "").trim();
  if (!needleRaw || !segments.length) return null;

  // Escalate cheapest-first, and try both boundary treatments at each strength
  // before loosening further: a Latin quote needs the joining space, a CJK one
  // needs its absence, and getting a strict match under either beats a loose
  // match under the other.
  const passes: Array<{
    soften: boolean;
    joinWithSpace: boolean;
    mode: QuoteRange["mode"];
  }> = [
    { soften: false, joinWithSpace: true, mode: "collapsed" },
    { soften: false, joinWithSpace: false, mode: "collapsed" },
    { soften: true, joinWithSpace: true, mode: "softened" },
    { soften: true, joinWithSpace: false, mode: "softened" },
  ];

  for (const pass of passes) {
    const haystack = project(segments, pass);
    const needle = projectQuote(needleRaw, pass);
    if (!needle) continue;
    const at = haystack.text.indexOf(needle);
    if (at >= 0) return rangeFrom(haystack, at, needle.length, pass.mode);
  }

  // Last resort: the longest prefix of the quote that does appear. A model often
  // quotes a sentence and then keeps writing its own words, so the head is the
  // reliable part — but a *fixed* head length is not, because it may itself run
  // past where the document stops matching. Binary search works because prefix
  // matching is monotonic: if a prefix of length L is present, so is every
  // shorter one.
  for (const joinWithSpace of [true, false]) {
    const haystack = project(segments, { soften: true, joinWithSpace });
    const needle = projectQuote(needleRaw, { soften: true, joinWithSpace });
    const longest = longestPrefixMatch(haystack.text, needle);
    if (longest) {
      return rangeFrom(haystack, longest.at, longest.length, "softened");
    }
  }
  return null;
}

/** Shortest prefix worth highlighting, and the share of the quote it must cover. */
const MIN_PREFIX_CHARS = 12;
const MIN_PREFIX_SHARE = 0.25;

function longestPrefixMatch(
  haystack: string,
  needle: string,
): { at: number; length: number } | null {
  const floor = Math.max(
    MIN_PREFIX_CHARS,
    Math.ceil(needle.length * MIN_PREFIX_SHARE),
  );
  if (needle.length < floor) return null;

  let low = floor;
  let high = needle.length;
  let best: { at: number; length: number } | null = null;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const at = haystack.indexOf(needle.slice(0, mid));
    if (at >= 0) {
      best = { at, length: mid };
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return best;
}

/**
 * Split plain unit text into marked and unmarked runs.
 *
 * Used by the text view (non-PDF materials), where highlights cannot be
 * geometric: the text reflows with the pane width, so a stored rectangle would
 * drift. Anchoring on the quote instead makes a mark reflow-proof — and it is
 * the same anchor the Markdown export uses, so the two always agree.
 *
 * Overlapping marks are resolved by taking the earliest, longest one and
 * skipping any that would intersect it; a nested highlight would otherwise
 * produce nested `<mark>` runs whose colours multiply into mud.
 */
export function segmentTextByQuotes<T extends { quote: string }>(
  text: string,
  marks: T[],
): Array<{ text: string; mark: T | null }> {
  if (!text) return [];
  const found: Array<{ start: number; end: number; mark: T }> = [];
  const haystack = text.toLowerCase();

  for (const mark of marks) {
    const needle = (mark.quote || "").trim().toLowerCase();
    if (needle.length < 2) continue;
    let at = haystack.indexOf(needle);
    if (at < 0) {
      // Fall back to whitespace-collapsed matching for a quote that was copied
      // out of a re-wrapped rendering of this same text.
      const collapsed = needle.replace(/\s+/g, " ");
      at = haystack.replace(/\s+/g, " ").indexOf(collapsed);
      if (at < 0) continue;
      // The offset is in collapsed space and cannot index `text`; skip rather
      // than mark the wrong run.
      continue;
    }
    found.push({ start: at, end: at + needle.length, mark });
  }

  found.sort((a, b) => a.start - b.start || b.end - a.end);
  const kept: typeof found = [];
  for (const candidate of found) {
    if (kept.some((k) => candidate.start < k.end && candidate.end > k.start)) {
      continue;
    }
    kept.push(candidate);
  }

  const runs: Array<{ text: string; mark: T | null }> = [];
  let cursor = 0;
  for (const range of kept) {
    if (range.start > cursor) {
      runs.push({ text: text.slice(cursor, range.start), mark: null });
    }
    runs.push({ text: text.slice(range.start, range.end), mark: range.mark });
    cursor = range.end;
  }
  if (cursor < text.length) {
    runs.push({ text: text.slice(cursor), mark: null });
  }
  return runs;
}

/** Collect the text nodes of a rendered layer, in document order. */
export function collectTextNodes(container: Element): Text[] {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current = walker.nextNode();
  while (current) {
    nodes.push(current as Text);
    current = walker.nextNode();
  }
  return nodes;
}

/**
 * Build a DOM Range for *quote* inside *container*, or null.
 *
 * Kept separate from {@link findQuoteRange} so the search logic stays pure and
 * this adapter stays trivial enough to eyeball.
 */
export function domRangeForQuote(
  container: Element,
  quote: string,
): Range | null {
  const nodes = collectTextNodes(container);
  if (!nodes.length) return null;
  const found = findQuoteRange(
    nodes.map((node) => node.textContent ?? ""),
    quote,
  );
  if (!found) return null;

  const startNode = nodes[found.start.segment];
  const endNode = nodes[found.end.segment];
  if (!startNode || !endNode) return null;

  const range = document.createRange();
  try {
    range.setStart(startNode, Math.min(found.start.offset, startNode.length));
    range.setEnd(endNode, Math.min(found.end.offset, endNode.length));
  } catch {
    return null;
  }
  return range.collapsed ? null : range;
}
