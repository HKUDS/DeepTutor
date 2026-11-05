/**
 * The article's speakable words, in reading order, with the DOM node each one
 * came from.
 *
 * Read-along needs to answer two questions against the *rendered* article, not
 * against the Markdown source: "which word did the reader click?" and "which
 * node should I paint for word N?". Both need the same enumeration, so it lives
 * here and is used by the click handler and the highlighter alike. Markdown
 * source is the wrong coordinate system — the renderer strips `**`, headings and
 * tables, so source offsets do not map onto what is on screen.
 *
 * Code is excluded: the voice does not read it as prose, and wrapping a
 * highlight inside a code block would misalign every later word.
 */
const SKIP_SELECTOR = "script,style,noscript,textarea,pre,code";

export interface SpeakableWord {
  word: string;
  node: Text;
  /** Offset of the word within its text node. */
  startInNode: number;
}

export interface SpeakableText {
  /** Words joined by single spaces — the exact string handed to the voice. */
  text: string;
  words: SpeakableWord[];
}

/** Enumerate the speakable words under `root` in document order. */
export function collectSpeakableText(root: HTMLElement): SpeakableText {
  const doc = root.ownerDocument;
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const words: SpeakableWord[] = [];

  while (walker.nextNode()) {
    const node = walker.currentNode as Text;
    const parent = node.parentElement;
    if (!parent) continue;
    if (parent.closest(SKIP_SELECTOR)) continue;
    const value = node.nodeValue;
    if (!value) continue;
    for (const match of value.matchAll(/\S+/g)) {
      words.push({
        word: match[0],
        node,
        startInNode: match.index ?? 0,
      });
    }
  }

  return { text: words.map((entry) => entry.word).join(" "), words };
}

/**
 * The word a caret position falls in, or the next one when the caret sits in
 * the whitespace between words.
 *
 * Returns -1 past the last word.
 */
export function wordIndexAtPoint(
  model: SpeakableText,
  node: Node | null,
  offset: number,
): number {
  if (!node || !model.words.length) return -1;
  for (let index = 0; index < model.words.length; index += 1) {
    const entry = model.words[index];
    if (entry.node !== node) continue;
    if (offset < entry.startInNode + entry.word.length) return index;
  }
  // The caret landed between nodes (or past this one); resume at the first word
  // that starts at or after it, which is what a reader means by "read from here".
  for (let index = 0; index < model.words.length; index += 1) {
    const entry = model.words[index];
    if (entry.node !== node) continue;
    if (entry.startInNode >= offset) return index;
  }
  return -1;
}

/** The first word covered by `range`, as an index into `model`. */
export function wordIndexForRangeStart(
  model: SpeakableText,
  range: Range,
): number {
  const { startContainer, startOffset } = range;
  if (startContainer.nodeType === Node.TEXT_NODE) {
    const hit = wordIndexAtPoint(model, startContainer, startOffset);
    if (hit >= 0) return hit;
  }
  // Element-level range start (e.g. selection began on a wrapper): pick the
  // first word whose node sits inside that element at or after the offset.
  const container = startContainer;
  const point = range.startContainer;
  for (let index = 0; index < model.words.length; index += 1) {
    const entry = model.words[index];
    if (point.contains(entry.node)) return index;
    if (container === entry.node) return index;
  }
  return 0;
}

/** A `Range` covering the word at `index`, or null when it is out of bounds. */
export function rangeForWordIndex(
  model: SpeakableText,
  index: number,
): Range | null {
  const entry = model.words[index];
  if (!entry) return null;
  const range = entry.node.ownerDocument.createRange();
  range.setStart(entry.node, entry.startInNode);
  range.setEnd(entry.node, entry.startInNode + entry.word.length);
  return range;
}

/**
 * The text to speak from `fromWord` onward, with the index the timeline's first
 * entry maps to on the page.
 *
 * The voice is given plain words rather than Markdown, so a heading reads as
 * "Preface" and not "hash hash Preface"; the returned `base` lets the highlighter
 * shift the server's 0-based timeline back onto the page's own numbering.
 */
export function speakableFrom(
  model: SpeakableText,
  fromWord: number,
): { text: string; base: number } {
  const base = Math.max(0, Math.min(fromWord, model.words.length));
  return {
    text: model.words
      .slice(base)
      .map((entry) => entry.word)
      .join(" "),
    base,
  };
}

/**
 * The word under a viewport point, as an index into `model`.
 *
 * Uses `caretPositionFromPoint` (with the WebKit-prefixed fallback) rather than
 * range hit-testing: it answers "where would a caret go if I clicked here?",
 * which is exactly what "read from this point" means — including clicks in the
 * margins or between words, where a click still reads from the nearest word.
 */
export function wordIndexFromPoint(
  model: SpeakableText,
  clientX: number,
  clientY: number,
): number {
  if (!model.words.length) return 0;
  const doc = model.words[0].node.ownerDocument;
  const withCaret = doc as Document & {
    caretPositionFromPoint?: (
      x: number,
      y: number,
    ) => { offsetNode: Node; offset: number } | null;
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
  };

  const caret = withCaret.caretPositionFromPoint?.(clientX, clientY);
  if (caret) {
    const hit = wordIndexAtPoint(model, caret.offsetNode, caret.offset);
    if (hit >= 0) return hit;
  }
  const range = withCaret.caretRangeFromPoint?.(clientX, clientY);
  if (range) {
    const hit = wordIndexAtPoint(model, range.startContainer, range.startOffset);
    if (hit >= 0) return hit;
  }

  // Fall back to the nearest word vertically: the click landed outside the
  // text (margin, trailing empty space), and "read from here" should start at
  // the first word the reader can see below it rather than doing nothing.
  let best = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < model.words.length; index += 1) {
    const entry = model.words[index];
    const box = entry.node.parentElement?.getBoundingClientRect();
    if (!box) continue;
    const distance = Math.abs(box.top - clientY) + Math.abs(box.left - clientX) / 1000;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = index;
    }
  }
  return best >= 0 ? best : 0;
}
