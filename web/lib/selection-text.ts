/**
 * The text of a selection in a rendered message, as the learner meant it.
 *
 * Rendered KaTeX reads back as Unicode glyphs that match nothing the model
 * wrote; these helpers put the original TeX back so a quoted passage carries
 * the same Markdown the message was written in.
 */

const MAX_SELECTED_TEXT_LENGTH = 12_000;

/** Collapse selection-only whitespace while preserving paragraph breaks. */
export function normalizeSelectedText(value: string): string {
  return value
    .replace(/\r\n?/g, "\n")
    .replace(/[\t\f\v ]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
    .slice(0, MAX_SELECTED_TEXT_LENGTH);
}

/** Wrap KaTeX's raw TeX annotation in the Markdown math delimiters we store. */
export function wrapLatexSource(tex: string, display: boolean): string {
  const body = tex.trim();
  if (!body) return "";
  return display ? `$$${body}$$` : `$${body}$`;
}

/** Read the original TeX embedded by KaTeX's default htmlAndMathml output. */
export function extractTexAnnotation(root: ParentNode): string | null {
  const annotation = root.querySelector(
    'annotation[encoding="application/x-tex"]',
  );
  const text = annotation?.textContent?.trim() ?? "";
  return text || null;
}

/** Test helper for the annotation emitted by KaTeX renderToString. */
export function extractTexAnnotationFromHtml(html: string): string | null {
  const match = html.match(
    /<annotation\b[^>]*\bencoding\s*=\s*["']application\/x-tex["'][^>]*>([\s\S]*?)<\/annotation>/i,
  );
  if (!match) return null;
  return decodeXmlText(match[1]).trim() || null;
}

/** Prefer original LaTeX over rendered KaTeX glyphs in a DOM selection. */
export function textFromDomSelection(selection: Selection | null): string {
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
    return "";
  }
  return normalizeSelectedText(
    rewriteRangePreferringKatexLatex(selection.getRangeAt(0)),
  );
}

function rewriteRangePreferringKatexLatex(range: Range): string {
  const roots = intersectingKatexRoots(range);
  if (roots.length === 0) return range.toString();

  if (roots.length === 1) {
    const root = roots[0];
    const start = nodeElement(range.startContainer);
    const end = nodeElement(range.endContainer);
    if (start && end && root.contains(start) && root.contains(end)) {
      const tex = extractTexAnnotation(root);
      if (tex) return wrapLatexSource(tex, isDisplayKatex(root));
    }
  }

  const holder = document.createElement("div");
  holder.appendChild(range.cloneContents());
  const cloned = Array.from(
    holder.querySelectorAll(".katex-display, .katex"),
  ).filter(
    (element) =>
      !(
        element.classList.contains("katex") && element.closest(".katex-display")
      ),
  );

  cloned.forEach((element, index) => {
    const live = roots[index] ?? null;
    const tex =
      (live ? extractTexAnnotation(live) : null) ||
      extractTexAnnotation(element);
    if (!tex) return;
    element.replaceWith(
      document.createTextNode(
        wrapLatexSource(tex, isDisplayKatex(live ?? element)),
      ),
    );
  });

  return holder.textContent ?? range.toString();
}

function intersectingKatexRoots(range: Range): Element[] {
  const scope = nodeElement(range.commonAncestorContainer);
  if (!scope) return [];
  const searchRoot =
    scope.closest("[data-chat-message-id], .md-renderer, .prose") ?? scope;
  return Array.from(
    searchRoot.querySelectorAll(".katex-display, .katex"),
  ).filter((element) => {
    if (
      element.classList.contains("katex") &&
      element.closest(".katex-display")
    ) {
      return false;
    }
    try {
      return range.intersectsNode(element);
    } catch {
      return false;
    }
  });
}

function isDisplayKatex(root: Element): boolean {
  return (
    root.classList.contains("katex-display") ||
    Boolean(root.closest(".katex-display"))
  );
}

function nodeElement(node: Node): Element | null {
  return node.nodeType === Node.ELEMENT_NODE
    ? (node as Element)
    : node.parentElement;
}

function decodeXmlText(value: string): string {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}
