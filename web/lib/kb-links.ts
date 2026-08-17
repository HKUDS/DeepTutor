import type { KnowledgeBaseFile } from "@/lib/knowledge-api";

/** Doc extensions we treat as "strip-able" when matching a link to a file. */
const DOC_EXTENSIONS = /\.(md|markdown|mdx|html|htm|adoc|asciidoc|rst)$/i;
/** Leading URL path segments that mark a locale; local docs are bilingual so
 *  both `/get-started/` and `/zh-cn/get-started/` resolve to the same page. */
const LOCALE_SEGMENT = /^(zh-cn|zh-tw|zh-hk|zh-sg|zh|en|ja|ko|de|fr|es|ru)$/;

/** Resolve `.` / `..` segments, dropping empties. */
function normalizeSegments(path: string): string[] {
  const out: string[] = [];
  for (const raw of path.split("/")) {
    const seg = raw.trim();
    if (seg === "" || seg === ".") continue;
    if (seg === "..") {
      out.pop();
      continue;
    }
    out.push(seg);
  }
  return out;
}

function candidatesFor(segments: string[]): string[] {
  const joined = segments.join("/");
  if (!joined) return ["index.md", "index.markdown"];
  return [
    `${joined}.md`,
    `${joined}.markdown`,
    `${joined}/index.md`,
    `${joined}/index.markdown`,
  ];
}

/**
 * Map a markdown link href to a local KB file path, or return null when the
 * link does not point at a document inside this KB.
 *
 * Handles three shapes:
 *  - Absolute docs URLs (`https://docs.example.com/get-started/pypi/`) — the
 *    pathname is matched against the local file tree.
 *  - Site-absolute paths (`/get-started/pypi/`).
 *  - Relative paths (`./pypi`, `../explore`, `docker.md`) resolved against
 *    the *currentPath*'s directory.
 *
 * Only http(s) URLs are ever considered internal; everything else (mailto,
 * ftp, …) is left alone. A link resolves only when an actual file exists, so
 * unrelated external links (GitHub, Discord, …) pass through untouched.
 */
export function resolveKbLink(
  href: string,
  currentPath: string,
  files: KnowledgeBaseFile[],
): string | null {
  if (!href) return null;
  const raw = href.split("#")[0].split("?")[0];
  if (!raw) return null;

  let segments: string[];
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(raw)) {
    let url: URL;
    try {
      url = new URL(raw);
    } catch {
      return null;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    segments = normalizeSegments(decodeURIComponent(url.pathname));
  } else {
    const baseDir = currentPath.includes("/")
      ? currentPath.slice(0, currentPath.lastIndexOf("/"))
      : "";
    segments = normalizeSegments(`${baseDir}/${raw}`);
  }

  // Drop a leading locale segment so localized links reach the same page.
  if (segments.length > 1 && LOCALE_SEGMENT.test(segments[0])) {
    segments.shift();
  }

  // Strip a doc extension from the last segment (`pypi.md` -> `pypi`).
  if (segments.length) {
    segments[segments.length - 1] = segments[segments.length - 1].replace(
      DOC_EXTENSIONS,
      "",
    );
  }
  // Drop a trailing `index` leaf (`get-started/index` -> `get-started`).
  if (
    segments.length > 1 &&
    segments[segments.length - 1].toLowerCase() === "index"
  ) {
    segments.pop();
  }

  const fileSet = new Set(
    files.filter((f) => f.type !== "folder").map((f) => f.name),
  );
  for (const candidate of candidatesFor(segments)) {
    if (fileSet.has(candidate)) return candidate;
  }
  return null;
}
