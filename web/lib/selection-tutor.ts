const MAX_SELECTED_TEXT_LENGTH = 12_000;
const MAX_SOURCE_MESSAGE_LENGTH = 24_000;

export interface SelectionTutorContext {
  selectedText: string;
  parentSessionId: string | null;
  sourceMessageId: number | null;
  sourceMessageText: string;
  sourceMessageRole: "user" | "assistant" | "system";
}

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

/** Keep Markdown/code layout intact while bounding the containing message. */
export function normalizeSourceMessageText(value: string): string {
  return value
    .replace(/\r\n?/g, "\n")
    .trim()
    .slice(0, MAX_SOURCE_MESSAGE_LENGTH);
}

/** Small deterministic id so selecting the same passage reuses its tutor tab. */
export function selectionTutorKey(
  selectedText: string,
  parentSessionId: string | null,
  sourceMessageId: number | null = null,
): string {
  let hash = 2166136261;
  const source = `${parentSessionId ?? "draft"}\u0000${sourceMessageId ?? "live"}\u0000${selectedText}`;
  for (let i = 0; i < source.length; i += 1) {
    hash ^= source.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return `selection-tutor:${parentSessionId ?? "draft"}:${(hash >>> 0).toString(36)}`;
}

export function buildSelectionTutorConfig(
  context: SelectionTutorContext,
): Record<string, unknown> {
  return {
    selection_tutor_context: {
      selected_text: normalizeSelectedText(context.selectedText),
      parent_session_id: context.parentSessionId ?? "",
      source_message_id: context.sourceMessageId,
      source_message_text: normalizeSourceMessageText(
        context.sourceMessageText,
      ),
      source_message_role: context.sourceMessageRole,
    },
  };
}

/**
 * Wrap KaTeX's raw TeX annotation so it matches Markdown math delimiters in
 * the stored assistant message (#1089).
 */
export function wrapLatexSource(tex: string, display: boolean): string {
  const body = tex.trim();
  if (!body) return "";
  return display ? `$$${body}$$` : `$${body}$`;
}

/**
 * Read the original TeX from a KaTeX root (``.katex`` / ``.katex-display``).
 * KaTeX's default ``htmlAndMathml`` output embeds it in an annotation node.
 */
export function extractTexAnnotation(root: ParentNode): string | null {
  const annotation = root.querySelector(
    'annotation[encoding="application/x-tex"]',
  );
  const text = annotation?.textContent?.trim() ?? "";
  return text || null;
}

/** Test helper: pull the annotation out of KaTeX ``renderToString`` HTML. */
export function extractTexAnnotationFromHtml(html: string): string | null {
  const match = html.match(
    /<annotation\b[^>]*\bencoding\s*=\s*["']application\/x-tex["'][^>]*>([\s\S]*?)<\/annotation>/i,
  );
  if (!match) return null;
  return decodeXmlText(match[1]).trim() || null;
}

/**
 * Prefer original LaTeX over KaTeX's rendered glyphs when reading a DOM
 * selection. Browser ``Selection#toString()`` otherwise yields Unicode math
 * (and broken line breaks for superscripts) that cannot be grounded against
 * the authoritative Markdown source message (#1089).
 */
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
  if (roots.length === 0) {
    return range.toString();
  }

  if (roots.length === 1) {
    const root = roots[0]!;
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
    (el) =>
      !(el.classList.contains("katex") && el.closest(".katex-display")),
  );

  cloned.forEach((el, index) => {
    const live = roots[index] ?? null;
    const tex =
      (live ? extractTexAnnotation(live) : null) || extractTexAnnotation(el);
    if (!tex) return;
    const display = isDisplayKatex(live ?? el);
    el.replaceWith(document.createTextNode(wrapLatexSource(tex, display)));
  });

  return holder.textContent ?? range.toString();
}

function intersectingKatexRoots(range: Range): Element[] {
  const ancestor = range.commonAncestorContainer;
  const scope = nodeElement(ancestor);
  if (!scope) return [];

  const searchRoot =
    scope.closest("[data-chat-message-id], .md-renderer, .prose") ?? scope;

  return Array.from(
    searchRoot.querySelectorAll(".katex-display, .katex"),
  ).filter((el) => {
    if (el.classList.contains("katex") && el.closest(".katex-display")) {
      return false;
    }
    try {
      return range.intersectsNode(el);
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
