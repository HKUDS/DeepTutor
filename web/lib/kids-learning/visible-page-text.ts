/**
 * Extract only the currently visible text from an EPUB iframe Document / Window viewport.
 * Avoids reading ahead into subsequent pages or reading previous pages in a multi-page chapter.
 */
export function getVisiblePageText(
  doc: Document | undefined,
  win: Window | undefined,
): string {
  if (!doc?.body) return "";
  const viewportWidth = win?.innerWidth || doc.documentElement?.clientWidth || 800;
  const viewportHeight = win?.innerHeight || doc.documentElement?.clientHeight || 600;

  // 1. Try block elements (p, h1..h6, li, blockquote)
  const blocks = doc.querySelectorAll("p, h1, h2, h3, h4, h5, h6, li, blockquote");
  const visibleBlocks: string[] = [];
  let foundWideBlock = false;

  for (const block of Array.from(blocks)) {
    const el = block as HTMLElement;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;

    // Check if element is completely on another column/page
    if (rect.right <= 2 || rect.left >= viewportWidth - 2) continue;
    if (rect.bottom <= 2 || rect.top >= viewportHeight - 2) continue;

    // If a single paragraph spans across multiple columns, switch to word-level granularity
    if (rect.width > viewportWidth * 1.2) {
      foundWideBlock = true;
      break;
    }

    const text = el.innerText || el.textContent || "";
    if (text.trim()) {
      visibleBlocks.push(text.trim());
    }
  }

  if (visibleBlocks.length > 0 && !foundWideBlock) {
    return visibleBlocks.join("\n");
  }

  // 2. If blocks span across columns or no blocks found, inspect visible word spans
  const spans = doc.querySelectorAll("[data-kids-word]");
  if (spans.length > 0) {
    const visibleWords: string[] = [];
    let lastParent: Element | null = null;

    for (const span of Array.from(spans)) {
      const el = span as HTMLElement;
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) continue;

      const isHorizontallyVisible = rect.right > 2 && rect.left < viewportWidth - 2;
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
          const match = punct.match(/^([.,!?:;'"”’\s]+)/);
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

  // 3. Fallback: direct visible children of body
  const visibleChildren: string[] = [];
  for (const child of Array.from(doc.body.children)) {
    const el = child as HTMLElement;
    if (["script", "style"].includes(el.tagName.toLowerCase())) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;

    if (
      rect.right > 2 &&
      rect.left < viewportWidth - 2 &&
      rect.bottom > 2 &&
      rect.top < viewportHeight - 2
    ) {
      const text = el.innerText || el.textContent || "";
      if (text.trim()) visibleChildren.push(text.trim());
    }
  }

  if (visibleChildren.length > 0) {
    return visibleChildren.join("\n");
  }

  // 4. Final fallback to document body
  return doc.body.innerText || doc.body.textContent || "";
}
