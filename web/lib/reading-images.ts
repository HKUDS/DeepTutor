/** One picture the viewer can show. */
export interface LightboxImage {
  src: string;
  alt: string;
}

/**
 * The pictures a reader can step through, and which one was clicked.
 *
 * Both readers need this and both had their own copy — the same nine lines,
 * differing only in the variable that held the root. Duplicated logic is how the
 * same defect lands in two places at once: the index was looked up by `src`, so a
 * unit with the same picture twice opened the first copy no matter which one was
 * clicked, and both readers had it.
 *
 * The index is taken from the **node**, not from the source: two pictures can
 * legitimately share a `src` (a repeated Markdown image, an EPUB decoration) and
 * they are different entries in the list.
 *
 * `root` is the scope that holds every picture of the unit — the scroll container
 * in the text reader, the section's iframe document in EPUB.
 */
export function collectLightboxImages(
  root: ParentNode | null | undefined,
  clicked: HTMLImageElement,
): { images: LightboxImage[]; index: number } {
  // Filter the *nodes* before computing the selected index. If an earlier
  // picture has no source, filtering only the image entries would shift the
  // list while leaving the clicked node's index unchanged.
  const nodes = Array.from(root?.querySelectorAll("img") ?? []).filter(
    (node) =>
      !node.closest("a[href]") &&
      Boolean(node.currentSrc || node.getAttribute("src")),
  );
  const images = nodes.map((node) => ({
    src: node.currentSrc || node.getAttribute("src") || "",
    alt: node.getAttribute("alt") ?? "",
  }));

  // The clicked node may have been filtered out (no source yet); fall back to
  // the first entry rather than reporting a negative index.
  const nodeIndex = nodes.indexOf(clicked);
  const index = nodeIndex < 0 ? 0 : nodeIndex;

  if (images.length === 0) {
    const src = clicked.currentSrc || clicked.getAttribute("src") || "";
    return { images: [{ src, alt: clicked.alt }], index: 0 };
  }
  return { images, index: Math.min(index, images.length - 1) };
}
