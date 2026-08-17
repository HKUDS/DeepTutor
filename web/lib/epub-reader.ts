export type EpubLayoutMode = "paginated" | "scrolled";
export type ReadingView = "original" | "study";

export const EPUB_LAYOUT_STORAGE_KEY = "deeptutor.immersiveReading.epubLayout";

export interface EpubSectionLike {
  id: string;
  source_href?: string;
  checkpoint_kind?: "chapter" | "chunk" | "none";
}

export function epubReaderOptions(layout: EpubLayoutMode): {
  manager: "default" | "continuous";
  flow: "paginated" | "scrolled";
} {
  if (layout === "scrolled") {
    return { manager: "continuous", flow: "scrolled" };
  }
  return { manager: "default", flow: "paginated" };
}

export function loadEpubLayoutPreference(): EpubLayoutMode {
  if (typeof window === "undefined") return "paginated";
  try {
    const value = window.localStorage.getItem(EPUB_LAYOUT_STORAGE_KEY);
    if (value === "scrolled" || value === "paginated") return value;
  } catch {
    /* ignore quota / private mode */
  }
  return "paginated";
}

export function saveEpubLayoutPreference(layout: EpubLayoutMode): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(EPUB_LAYOUT_STORAGE_KEY, layout);
  } catch {
    /* ignore quota / private mode */
  }
}

export function defaultReadingView(options: {
  sourceFormat?: string;
  viewParam?: string | null;
  experienceMode?: string | null;
}): ReadingView {
  if ((options.sourceFormat || "").toLowerCase() !== "epub") {
    return "study";
  }
  if (options.experienceMode === "kids") {
    return "study";
  }
  if (options.viewParam === "study") return "study";
  return "original";
}

export function normalizeEpubHref(href: string): string {
  const raw = (href || "").trim().replace(/\\/g, "/");
  if (!raw) return "";
  const hashIndex = raw.indexOf("#");
  const pathWithQuery = hashIndex >= 0 ? raw.slice(0, hashIndex) : raw;
  const fragment = hashIndex >= 0 ? raw.slice(hashIndex + 1) : "";
  let path = pathWithQuery.split("?")[0];
  try {
    path = decodeURIComponent(path);
  } catch {
    /* keep raw path */
  }
  path = path.replace(/^\.\//, "");
  const parts: string[] = [];
  for (const part of path.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      parts.pop();
      continue;
    }
    parts.push(part);
  }
  const normalized = parts.join("/");
  return fragment ? `${normalized}#${fragment}` : normalized;
}

export function epubHrefPath(href: string): string {
  return normalizeEpubHref(href).split("#")[0] || "";
}

export function epubHrefsMatch(left: string, right: string): boolean {
  const a = epubHrefPath(left);
  const b = epubHrefPath(right);
  if (!a || !b) return false;
  if (a === b) return true;
  if (a.endsWith(`/${b}`) || b.endsWith(`/${a}`)) return true;
  const aName = a.split("/").pop() || "";
  const bName = b.split("/").pop() || "";
  return Boolean(aName && aName === bName);
}

export function resolveStudySectionId(
  sections: EpubSectionLike[],
  href: string,
  preferredSectionId = "",
): string {
  const matches = sections.filter((section) => epubHrefsMatch(section.source_href || "", href));
  if (preferredSectionId && matches.some((section) => section.id === preferredSectionId)) {
    return preferredSectionId;
  }
  const leaf = matches.find((section) => section.checkpoint_kind !== "none") || matches[0];
  return leaf?.id || preferredSectionId || sections[0]?.id || "";
}

export function originalDocumentUrl(documentId: string): string {
  return `/api/v1/immersive-reading/documents/${encodeURIComponent(documentId)}/original`;
}

export function immersiveReadingPath(
  documentId: string,
  options: { view?: ReadingView | null; section?: string | null } = {},
): string {
  const params = new URLSearchParams();
  params.set("book", documentId);
  if (options.view) params.set("view", options.view);
  if (options.section) params.set("section", options.section);
  return `/immersive-reading?${params.toString()}`;
}

export function epubScrollPercent(percentage: number, page?: number, total?: number): number {
  if (total && total > 0 && page && page > 0) {
    return Math.max(0, Math.min(100, ((page - 1) / total) * 100));
  }
  return Math.max(0, Math.min(100, percentage * 100));
}
