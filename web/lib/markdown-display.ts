"use client";

const ZERO_WIDTH_REGEX = /[\u200B-\u200D\uFEFF]/g;
const EMPTY_DETAILS_REGEX =
  /<details(?:\s[^>]*)?>\s*(<summary(?:\s[^>]*)?>\s*(?:&nbsp;|\s|<br\s*\/?>)*\s*<\/summary>\s*)?<\/details>/gi;
const EMPTY_SUMMARY_REGEX =
  /<summary(?:\s[^>]*)?>\s*(?:&nbsp;|\s|<br\s*\/?>)*\s*<\/summary>/gi;
const EMPTY_PROGRESS_REGEX =
  /<progress(?:\s[^>]*)?>\s*(?:&nbsp;|\s|<br\s*\/?>)*\s*<\/progress>/gi;
const RAW_INPUT_REGEX = /<input(?:\s[^>]*)?>/gi;
const EMPTY_FORM_CONTROL_REGEX =
  /<(textarea|select|button|meter)(?:\s[^>]*)?>\s*(?:&nbsp;|\s|<br\s*\/?>)*\s*<\/\1>/gi;
const EMPTY_FENCED_CODE_BLOCK_REGEX = /```[^\n`]*\n?\s*```/g;
const EMPTY_HTML_BLOCK_REGEX =
  /<(p|div|section|article|aside|blockquote)(?:\s[^>]*)?>\s*(?:&nbsp;|\s|<br\s*\/?>)*\s*<\/\1>/gi;
const HTML_TABLE_REGEX = /<table(?:\s[^>]*)?>[\s\S]*?<\/table>/gi;

function stripInvisibleCharacters(value: string): string {
  return value.replace(ZERO_WIDTH_REGEX, "");
}

// Tags that the renderer (rehype-raw + react-markdown) is allowed to render
// as actual HTML/SVG/MathML elements. Any other `<word>` looking token
// (e.g. LLM-pseudo-tags like <mem>, <think>, <tool_call>, <answer>, <search>)
// is escaped into inline code so the browser does not warn about unknown
// custom elements with lowercase names.
const ALLOWED_HTML_TAGS = new Set<string>([
  // structural
  "p",
  "div",
  "span",
  "section",
  "article",
  "aside",
  "header",
  "footer",
  "main",
  "nav",
  "address",
  "dialog",
  // text-level
  "a",
  "em",
  "strong",
  "b",
  "i",
  "u",
  "s",
  "del",
  "ins",
  "small",
  "sub",
  "sup",
  "mark",
  "kbd",
  "code",
  "samp",
  "var",
  "q",
  "cite",
  "abbr",
  "time",
  "wbr",
  "ruby",
  "rt",
  "rp",
  "bdi",
  "bdo",
  // line-level
  "br",
  "hr",
  // lists
  "ol",
  "ul",
  "li",
  "dl",
  "dt",
  "dd",
  // headings
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  // block quotes / pre
  "blockquote",
  "pre",
  "figure",
  "figcaption",
  // tables
  "table",
  "thead",
  "tbody",
  "tfoot",
  "tr",
  "th",
  "td",
  "caption",
  "col",
  "colgroup",
  // passive media
  "img",
  "video",
  "audio",
  "source",
  "picture",
  "track",
  // disclosure / lightweight status
  "details",
  "summary",
  "progress",
  "meter",
  // mathml
  "math",
  "mi",
  "mn",
  "mo",
  "ms",
  "mtext",
  "mrow",
  "mfrac",
  "msup",
  "msub",
  "msubsup",
  "munder",
  "mover",
  "munderover",
  "mroot",
  "msqrt",
  "menclose",
  "mspace",
  "mtable",
  "mtr",
  "mtd",
]);

const HTML_LIKE_TAG_REGEX = /<\/?([A-Za-z][A-Za-z0-9_-]*)\b[^<>]*?\/?>/g;
const FENCED_CODE_BLOCK_REGEX = /```[\s\S]*?```/g;
const INLINE_CODE_SPAN_REGEX = /`[^`\n]*`/g;
// Display math (\[…\], \(…\), $$…$$) plus single-dollar inline math ($…$).
// The inline form mirrors remark-math's "tight" rule — no space just inside the
// delimiters — so prose currency like "$5 and $10" is not swallowed, while real
// inline math ($x = [1, 5, 9]$) is protected from citation linkification.
const MATH_SPAN_REGEX =
  /\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$\$[\s\S]*?\$\$|\$(?!\s)(?:\\.|[^$\n])*?(?<!\s)\$/g;
const PROTECTED_SPAN_REGEX = /```[\s\S]*?```|`[^`\n]*`/g;
const PROTECTED_PLACEHOLDER_REGEX = /\u0000PROTECTED_(\d+)\u0000/g;
const HTML_ATTR_VALUE = /(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+)/.source;
const HTML_EVENT_ATTR_REGEX = new RegExp(
  String.raw`\s+on[a-z]+\s*=\s*${HTML_ATTR_VALUE}`,
  "gi",
);
const HTML_STYLE_ATTR_REGEX = new RegExp(
  String.raw`\s+style\s*=\s*${HTML_ATTR_VALUE}`,
  "gi",
);
const HTML_SRCDOC_ATTR_REGEX = new RegExp(
  String.raw`\s+srcdoc\s*=\s*${HTML_ATTR_VALUE}`,
  "gi",
);
const HTML_UNSAFE_URL_ATTR_REGEX =
  /\s+(href|src|xlink:href|formaction)\s*=\s*(?:"\s*(?:javascript:|data:text\/html|data:image\/svg\+xml)[^"]*"|'\s*(?:javascript:|data:text\/html|data:image\/svg\+xml)[^']*'|(?:javascript:|data:text\/html|data:image\/svg\+xml)[^\s"'=<>`]+)/gi;
// ``attachment`` lets the model place generated-file cards inline via
// ``[label](attachment:NAME)`` links (see components/common/InlineFileCard.tsx).
// The renderers always intercept these — they're never emitted as real
// navigable anchors — so allow-listing the scheme keeps the href intact
// without widening the attack surface.
const SAFE_MARKDOWN_PROTOCOL_REGEX = /^(https?|ircs?|mailto|xmpp|attachment)$/i;
const SAFE_RASTER_DATA_IMAGE_REGEX =
  /^data:image\/(?:png|jpe?g|gif|webp|bmp|tiff?|avif);base64,[a-z0-9+/=\s]+$/i;

function isMarkdownImageSrc(key?: string, node?: unknown): boolean {
  const tagName =
    node && typeof node === "object" && "tagName" in node
      ? String((node as { tagName?: unknown }).tagName || "").toLowerCase()
      : "";
  return key === "src" && tagName === "img";
}

/**
 * react-markdown's default URL policy intentionally strips all `data:`
 * URLs. Knowledge-base previews should still render self-contained markdown
 * screenshots, so allow only passive raster image data URLs on `<img src>`.
 */
export function markdownUrlTransform(
  value: string,
  key?: string,
  node?: unknown,
): string {
  if (
    isMarkdownImageSrc(key, node) &&
    SAFE_RASTER_DATA_IMAGE_REGEX.test(value)
  ) {
    return value;
  }

  const colon = value.indexOf(":");
  const questionMark = value.indexOf("?");
  const numberSign = value.indexOf("#");
  const slash = value.indexOf("/");

  if (
    colon === -1 ||
    (slash !== -1 && colon > slash) ||
    (questionMark !== -1 && colon > questionMark) ||
    (numberSign !== -1 && colon > numberSign) ||
    SAFE_MARKDOWN_PROTOCOL_REGEX.test(value.slice(0, colon))
  ) {
    return value;
  }

  return "";
}

function sanitizeAllowedHtmlTag(tag: string): string {
  return tag
    .replace(HTML_EVENT_ATTR_REGEX, "")
    .replace(HTML_STYLE_ATTR_REGEX, "")
    .replace(HTML_SRCDOC_ATTR_REGEX, "")
    .replace(HTML_UNSAFE_URL_ATTR_REGEX, "");
}

function escapeUnknownHtmlTags(content: string): string {
  if (!content || (!content.includes("<") && !content.includes(">"))) {
    return content;
  }
  const protectedSpans: string[] = [];
  const masked = content.replace(PROTECTED_SPAN_REGEX, (match) => {
    protectedSpans.push(match);
    return `\u0000PROTECTED_${protectedSpans.length - 1}\u0000`;
  });
  const escaped = masked.replace(HTML_LIKE_TAG_REGEX, (match, name: string) => {
    const lower = String(name).toLowerCase();
    if (ALLOWED_HTML_TAGS.has(lower)) return sanitizeAllowedHtmlTag(match);
    // Already wrapped in backticks (would happen if the source already
    // protected a similar token earlier in the string).
    return `\`${match}\``;
  });
  return escaped.replace(
    PROTECTED_PLACEHOLDER_REGEX,
    (_, idx: string) => protectedSpans[Number(idx)] ?? "",
  );
}

export function escapeUnknownHtmlTagsForDisplay(content: string): string {
  if (!content) return "";
  return escapeUnknownHtmlTags(
    stripInvisibleCharacters(String(content)).replace(/\r\n/g, "\n"),
  );
}

function stripDisplaySyntax(value: string): string {
  return stripInvisibleCharacters(String(value))
    .replace(/&nbsp;/gi, " ")
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<[^>]+>/g, "")
    .replace(/!\[(.*?)\]\([^)]+\)/g, "$1")
    .replace(/\[(.*?)\]\([^)]+\)/g, "$1")
    .replace(/[`*_~]/g, "")
    .trim();
}

function splitMarkdownTableCells(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  if (!trimmed) return [""];
  return trimmed.split("|");
}

function isMarkdownTableSeparator(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed.includes("|")) return false;
  const cells = splitMarkdownTableCells(trimmed);
  return (
    cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()))
  );
}

function isMarkdownTableStart(lines: string[], index: number): boolean {
  if (index + 1 >= lines.length) return false;

  const header = lines[index]?.trim() || "";
  const separator = lines[index + 1]?.trim() || "";
  if (
    !header ||
    !separator ||
    !header.includes("|") ||
    !isMarkdownTableSeparator(separator)
  ) {
    return false;
  }

  return (
    splitMarkdownTableCells(header).length ===
    splitMarkdownTableCells(separator).length
  );
}

function isMarkdownTableBodyRow(line: string, columnCount: number): boolean {
  const trimmed = line.trim();
  if (!trimmed || !trimmed.includes("|")) return false;
  return splitMarkdownTableCells(trimmed).length === columnCount;
}

function isEmptyMarkdownTable(lines: string[]): boolean {
  return lines
    .filter((_, index) => index !== 1)
    .every((line) =>
      splitMarkdownTableCells(line).every(
        (cell) => stripDisplaySyntax(cell).length === 0,
      ),
    );
}

function removeEmptyMarkdownTables(content: string): string {
  const lines = content.split("\n");
  const cleaned: string[] = [];

  for (let index = 0; index < lines.length; ) {
    if (!isMarkdownTableStart(lines, index)) {
      cleaned.push(lines[index]);
      index += 1;
      continue;
    }

    const columnCount = splitMarkdownTableCells(lines[index]).length;
    let end = index + 2;
    while (
      end < lines.length &&
      isMarkdownTableBodyRow(lines[end], columnCount)
    ) {
      end += 1;
    }

    const tableLines = lines.slice(index, end);
    if (!isEmptyMarkdownTable(tableLines)) {
      cleaned.push(...tableLines);
    }
    index = end;
  }

  return cleaned.join("\n");
}

function removeEmptyHtmlTables(content: string): string {
  return content.replace(HTML_TABLE_REGEX, (block) =>
    stripDisplaySyntax(block) ? block : "",
  );
}

const PREFIXED_CIT = String.raw`(?:web|rag|code|src)-\d+`;
const NUMERIC_CIT = String.raw`\d+`;
const RESEARCH_CIT = String.raw`(?:CIT-\d+-\d+|PLAN-\d+)`;
const SINGLE_CIT = `(?:${PREFIXED_CIT}|${NUMERIC_CIT}|${RESEARCH_CIT})`;
const MULTI_CIT = `${SINGLE_CIT}(?:\\s*,\\s*${SINGLE_CIT})*`;

const INLINE_CITATION_REGEX = new RegExp(
  String.raw`(?<!\*\*|\[)\[(${MULTI_CIT})\](?!\(|:)`,
  "g",
);

const ESCAPED_CITATION_LINK_REGEX = new RegExp(
  String.raw`\\?\[(${SINGLE_CIT})\\?\]\s*\(#references\s+["` +
    "\u201c" +
    String.raw`]citation["` +
    "\u201d" +
    String.raw`]\)`,
  "g",
);
const EXISTING_RESEARCH_CITATION_LINK_REGEX = new RegExp(
  String.raw`\[(${RESEARCH_CIT})\]\(#(ref-[a-z0-9_-]+)\s+["` +
    "\u201c" +
    String.raw`]citation["` +
    "\u201d" +
    String.raw`]\)`,
  "gi",
);
const REFERENCE_LIST_START_REGEX =
  /^##\s+(References|参考文献|参考资料)|<details\b[^>]*\bid=["']references["'][^>]*>/im;
const REFERENCE_LIST_DATA_ID_REGEX =
  /data-citation-id=["'](CIT-\d+-\d+|PLAN-\d+)["']/gi;
const RESEARCH_CITATION_ID_TEXT_REGEX = /\b(CIT-\d+-\d+|PLAN-\d+)\b/gi;

/**
 * Decide whether a bracketed comma list is a citation group rather than a plain
 * number array. Prefixed (`web-1`/`rag-1`/…) and research (`CIT-…`/`PLAN-…`)
 * tokens are unambiguous citations. Bare-numeric lists are ambiguous with data
 * arrays (`[1, 5, 9, 5, 3, 2, 7]`), so they only count as a citation group when
 * they look like one: a small set of *distinct* numbers. This keeps `[1]` and
 * `[1, 2, 3]` working while leaving real arrays untouched.
 */
function isLikelyCitationList(refs: string): boolean {
  const ids = String(refs || "")
    .split(/\s*,\s*/)
    .map((id) => id.trim())
    .filter(Boolean);
  if (!ids.length) return false;
  if (ids.some((id) => !/^\d+$/.test(id))) return true;
  if (ids.length > 3) return false;
  return new Set(ids).size === ids.length;
}

function unwrapBacktickedCitations(content: string): string {
  return content.replace(
    new RegExp(
      "`(\\[(" +
        MULTI_CIT +
        ')\\](?:\\s*\\(#(?:references|ref-[a-z0-9_-]+)\\s+["\\u201c]citation["\\u201d]\\))?)`',
      "g",
    ),
    // Only strip the backticks when the bracket is a citation group; a
    // backticked number array (`[1, 5, 9, 5, 3, 2, 7]`) stays code.
    (match, inner: string, refs: string) =>
      isLikelyCitationList(refs) ? inner : match,
  );
}

function linkifyCitations(content: string): string {
  const citationNumbers = buildResearchCitationNumberMap(content);
  const refSectionIdx = content.search(REFERENCE_LIST_START_REGEX);
  const body = refSectionIdx >= 0 ? content.slice(0, refSectionIdx) : content;
  const tail = refSectionIdx >= 0 ? content.slice(refSectionIdx) : "";

  // Normalize existing citation links that may have escaped brackets or smart quotes
  let linked = body.replace(ESCAPED_CITATION_LINK_REGEX, (_match, id: string) =>
    formatCitationLinks(id.trim(), citationNumbers),
  );

  linked = linked.replace(
    EXISTING_RESEARCH_CITATION_LINK_REGEX,
    (_match, id: string) => formatCitationLinks(id.trim(), citationNumbers),
  );

  // Convert bare [web-1] / [rag-1] / [1] / [1, 3] references to a single citation
  // link — but only when the bracket is a citation group, not a number array.
  linked = linked.replace(INLINE_CITATION_REGEX, (match, refs: string) => {
    return isLikelyCitationList(refs)
      ? formatCitationLinks(refs, citationNumbers)
      : match;
  });

  // Handle escaped bare citations like \[web-1\] or \[1\] that linkifyCitations missed
  linked = linked.replace(
    new RegExp(String.raw`\\\[(${MULTI_CIT})\\\](?!\s*\()`, "g"),
    (match, refs: string) => {
      return isLikelyCitationList(refs)
        ? formatCitationLinks(refs, citationNumbers)
        : match;
    },
  );

  // Remove stray space before trailing punctuation after citations
  linked = linked.replace(
    /(\(#(?:references|ref-[a-z0-9_-]+)\s+"citation"\))\s+([.。,，;:!?])/gi,
    "$1$2",
  );

  return linked + tail;
}

export function citationAnchorIdFor(id: string): string | null {
  const normalized = String(id || "").trim();
  if (!/^(?:CIT-\d+-\d+|PLAN-\d+)$/i.test(normalized)) return null;
  return `ref-${normalized.toLowerCase().replace(/[^a-z0-9_-]+/g, "-")}`;
}

export function citationHrefForId(id: string): string {
  const anchor = citationAnchorIdFor(id);
  return anchor ? `#${anchor}` : "#references";
}

function citationHrefForRefs(refs: string): string {
  const ids = String(refs || "")
    .split(/\s*,\s*/)
    .map((id) => id.trim())
    .filter(Boolean);
  return ids.length === 1 ? citationHrefForId(ids[0]) : "#references";
}

function isResearchCitationId(id: string): boolean {
  return /^(?:CIT-\d+-\d+|PLAN-\d+)$/i.test(String(id || "").trim());
}

function buildResearchCitationNumberMap(content: string): Map<string, number> {
  const map = new Map<string, number>();
  const refSectionIdx = content.search(REFERENCE_LIST_START_REGEX);
  const scan = refSectionIdx >= 0 ? content.slice(refSectionIdx) : content;

  const add = (id: string) => {
    const normalized = String(id || "").trim();
    if (!isResearchCitationId(normalized) || map.has(normalized)) return;
    map.set(normalized, map.size + 1);
  };

  for (const match of scan.matchAll(REFERENCE_LIST_DATA_ID_REGEX)) {
    add(match[1] || "");
  }
  if (map.size === 0) {
    for (const match of scan.matchAll(RESEARCH_CITATION_ID_TEXT_REGEX)) {
      add(match[1] || "");
    }
  }
  return map;
}

function formatCitationLinks(
  refs: string,
  citationNumbers: Map<string, number>,
): string {
  const ids = String(refs || "")
    .split(/\s*,\s*/)
    .map((id) => id.trim())
    .filter(Boolean);
  if (!ids.length) return `[${refs}](#references "citation")`;
  if (ids.every(isResearchCitationId)) {
    return ids
      .map((id) => {
        const number = citationNumbers.get(id) ?? Number.NaN;
        const label = Number.isFinite(number) ? String(number) : id;
        return `[${label}](${citationHrefForId(id)} "citation")`;
      })
      .join("");
  }
  const label = ids.join(", ");
  return `[${label}](${citationHrefForRefs(label)} "citation")`;
}

function maskProtectedSpans(
  content: string,
  regex: RegExp,
  label: string,
): { masked: string; restore: (value: string) => string } {
  const protectedSpans: string[] = [];
  const masked = content.replace(regex, (match) => {
    protectedSpans.push(match);
    return `\u0000${label}_${protectedSpans.length - 1}\u0000`;
  });
  const placeholderRegex = new RegExp(`\\u0000${label}_(\\d+)\\u0000`, "g");
  return {
    masked,
    restore: (value: string) =>
      value.replace(
        placeholderRegex,
        (_match, idx: string) => protectedSpans[Number(idx)] ?? "",
      ),
  };
}

function linkifyCitationsOutsideCode(content: string): string {
  const fenced = maskProtectedSpans(
    content,
    FENCED_CODE_BLOCK_REGEX,
    "FENCED_CODE",
  );
  const math = maskProtectedSpans(fenced.masked, MATH_SPAN_REGEX, "MATH");
  const unwrapped = unwrapBacktickedCitations(math.masked);
  const inline = maskProtectedSpans(
    unwrapped,
    INLINE_CODE_SPAN_REGEX,
    "INLINE_CODE",
  );
  return fenced.restore(
    math.restore(inline.restore(linkifyCitations(inline.masked))),
  );
}

export function normalizeMarkdownForDisplay(content: string): string {
  if (!content) return "";

  const normalized = stripInvisibleCharacters(String(content))
    .replace(/\r\n/g, "\n")
    .replace(EMPTY_DETAILS_REGEX, "")
    .replace(EMPTY_SUMMARY_REGEX, "")
    .replace(EMPTY_PROGRESS_REGEX, "")
    .replace(RAW_INPUT_REGEX, "")
    .replace(EMPTY_FORM_CONTROL_REGEX, "")
    .replace(EMPTY_HTML_BLOCK_REGEX, "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/^\n+|\n+$/g, "");

  const cleaned = removeEmptyMarkdownTables(
    removeEmptyHtmlTables(normalized),
  ).replace(/\n{3,}/g, "\n\n");
  const safe = escapeUnknownHtmlTagsForDisplay(cleaned);
  return linkifyCitationsOutsideCode(safe);
}

/**
 * Strip machine annotations the model occasionally echoes from tool results
 * into its answer — e.g. a standalone "[Generated artifacts: foo.pdf]" line.
 * The files themselves render as dedicated cards under the message, so the
 * annotation is pure noise in the prose.
 */
export function stripArtifactAnnotations(content: string): string {
  if (!content.includes("Generated artifacts")) return content;
  return content
    .replace(/^\s*\[Generated artifacts?:[^\]]*\]\s*$/gim, "")
    .trim();
}

export function hasVisibleMarkdownContent(content: string): boolean {
  const normalized = normalizeMarkdownForDisplay(content);
  if (!normalized.trim()) return false;

  const withoutEmptyBlocks = normalized
    .replace(EMPTY_FENCED_CODE_BLOCK_REGEX, "")
    .replace(/<[^>]+>/g, "")
    .replace(/\[(.*?)\]\([^)]+\)/g, "$1")
    .replace(/!\[(.*?)\]\([^)]+\)/g, "$1")
    .replace(/^[\s>*\-+|#`]+$/gm, "");

  return stripInvisibleCharacters(withoutEmptyBlocks).trim().length > 0;
}
