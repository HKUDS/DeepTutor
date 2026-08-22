/**
 * Extract only the currently visible text from an EPUB iframe Document / Window viewport.
 * Avoids reading ahead into subsequent pages or reading previous pages in a multi-page chapter.
 */
export function getVisiblePageText(
  doc: Document | undefined,
  win: Window | undefined,
  rendition?: any,
): string {
  if (!doc?.body) return "";

  // 1. Try exact rendition range if rendition is provided or location exists
  if (rendition) {
    try {
      const loc = rendition.currentLocation?.();
      const startCfi = loc?.start?.cfi;
      const endCfi = loc?.end?.cfi;
      if (startCfi && endCfi) {
        const startRange = rendition.getRange?.(startCfi);
        const endRange = rendition.getRange?.(endCfi);
        if (startRange && endRange) {
          const ownerDoc = startRange.startContainer?.ownerDocument || doc;
          const pageRange = ownerDoc.createRange();
          pageRange.setStart(startRange.startContainer, startRange.startOffset);
          pageRange.setEnd(endRange.endContainer, endRange.endOffset);
          const rangeText = pageRange.toString().trim();
          if (rangeText && rangeText.length > 5) {
            return rangeText;
          }
        }
      }
    } catch {}
  }

  // 2. Calculate horizontal offset in paginated multi-column layout
  const viewportWidth = win?.innerWidth || doc.documentElement?.clientWidth || 800;
  const viewportHeight = win?.innerHeight || doc.documentElement?.clientHeight || 600;

  let startX = 0;
  try {
    const loc = rendition?.currentLocation?.();
    const pageNumber = loc?.start?.displayed?.page;
    if (typeof pageNumber === "number" && pageNumber >= 1) {
      startX = (pageNumber - 1) * viewportWidth;
    }
  } catch {}

  const endX = startX + viewportWidth;

  // 3. Inspect block elements inside [startX, endX]
  const blocks = doc.querySelectorAll("p, h1, h2, h3, h4, h5, h6, li, blockquote, div.bodycontent-text");
  const visibleBlocks: string[] = [];

  for (const block of Array.from(blocks)) {
    const el = block as HTMLElement;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;

    // Check if element intersects [startX, endX] and vertical bounds
    const isHorizontallyVisible = rect.right > startX + 2 && rect.left < endX - 2;
    const isVerticallyVisible = rect.bottom > 2 && rect.top < viewportHeight - 2;

    if (isHorizontallyVisible && isVerticallyVisible) {
      const text = el.innerText || el.textContent || "";
      if (text.trim()) {
        visibleBlocks.push(text.trim());
      }
    }
  }

  if (visibleBlocks.length > 0) {
    return visibleBlocks.join("\n");
  }

  // 4. Inspect visible word spans
  const spans = doc.querySelectorAll("[data-kids-word]");
  if (spans.length > 0) {
    const visibleWords: string[] = [];
    let lastParent: Element | null = null;

    for (const span of Array.from(spans)) {
      const el = span as HTMLElement;
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) continue;

      const isHorizontallyVisible = rect.right > startX + 2 && rect.left < endX - 2;
      const isVerticallyVisible = rect.bottom > 2 && rect.top < viewportHeight - 2;

      if (isHorizontallyVisible && isVerticallyVisible) {
        const parent = el.closest("p, h1, h2, h3, h4, h5, h6, li, blockquote, div");
        if (lastParent && parent !== lastParent) {
          visibleWords.push("\n");
        }
        lastParent = parent;

        let wordWithPunctuation = el.textContent || "";
        const nextSibling = el.nextSibling;
        if (nextSibling && nextSibling.nodeType === 3) {
          const punct = nextSibling.nodeValue || "";
          const match = punct.match(/^([.,!?:;\x27"”’\s]+)/);
          if (match) {
            wordWithPunctuation += match[1].trimEnd();
          }
        }
        visibleWords.push(wordWithPunctuation);
      }
    }

    const pageText = visibleWords.join(" ").replace(/\s*\n\s*/g, "\n").trim();
    if (pageText) return pageText;
  }

  // 5. Final fallback to document body
  return doc.body.innerText || doc.body.textContent || "";
}
