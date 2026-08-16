const FENCED_CODE_RE = /```[\s\S]*?```/g
const INLINE_CODE_RE = /`[^`\n]*`/g
const DISPLAY_MATH_RE = /\$\$[\s\S]*?\$\$/g
const HTML_TAG_RE =
  /<\/?(?!(?:https?|mailto):)[A-Za-z][A-Za-z0-9-]*\b[^>]*>/g
const LATEXISH_INLINE_MATH_RE =
  /\$(?!\s)(?:\\.|[^$\n])*?[\\^_{}=](?:\\.|[^$\n])*?(?<!\s)\$/g
const CURRENCY_DOLLAR_RE = /\$(\d[\d,]*(?:\.\d+)?)(?![\d^_{\\=])/g
const SAFE_PROTOCOL_RE = /^(https?|mailto)$/i
const SAFE_RASTER_DATA_RE =
  /^data:image\/(?:png|jpe?g|gif|webp|bmp|tiff?|avif);base64,[a-z0-9+/=\s]+$/i

type Masked = {
  masked: string
  restore: (value: string) => string
}

function maskSpans(content: string, regex: RegExp, label: string): Masked {
  const spans: string[] = []
  const masked = content.replace(regex, (match) => {
    spans.push(match)
    return `\0${label}_${spans.length - 1}\0`
  })
  const placeholder = new RegExp(`\\0${label}_(\\d+)\\0`, 'g')
  return {
    masked,
    restore: (value) =>
      value.replace(placeholder, (_m, idx: string) => spans[Number(idx)] ?? ''),
  }
}

function withProtectedSpans(
  content: string,
  rewrite: (value: string) => string,
  includeDisplayMath = false,
): string {
  const fenced = maskSpans(content, FENCED_CODE_RE, 'FENCE')
  const math = includeDisplayMath
    ? maskSpans(fenced.masked, DISPLAY_MATH_RE, 'MATH')
    : { masked: fenced.masked, restore: (v: string) => v }
  const inline = maskSpans(math.masked, INLINE_CODE_RE, 'INLINE')
  return fenced.restore(math.restore(inline.restore(rewrite(inline.masked))))
}

export function convertLatexDelimiters(content: string): string {
  if (!content.includes('\\(') && !content.includes('\\[')) return content
  return withProtectedSpans(content, (value) =>
    value
      .replace(/\\\[([\s\S]*?)\\\]/g, (_m, expr: string) => `\n$$\n${expr}\n$$\n`)
      .replace(/\\\(([\s\S]*?)\\\)/g, (_m, expr: string) => `$${expr}$`),
  )
}

export function escapeCurrencyDollars(content: string): string {
  if (!content.includes('$')) return content
  const fenced = maskSpans(content, FENCED_CODE_RE, 'FENCE')
  const display = maskSpans(fenced.masked, DISPLAY_MATH_RE, 'MATH')
  const inlineMath = maskSpans(display.masked, LATEXISH_INLINE_MATH_RE, 'IMATH')
  const inline = maskSpans(inlineMath.masked, INLINE_CODE_RE, 'INLINE')
  const rewritten = inline.masked.replace(CURRENCY_DOLLAR_RE, '\\$$$1')
  return fenced.restore(
    display.restore(inlineMath.restore(inline.restore(rewritten))),
  )
}

export function escapeLiteralHtml(content: string): string {
  if (!content.includes('<')) return content
  return withProtectedSpans(content, (value) =>
    value.replace(HTML_TAG_RE, (tag) =>
      tag.replace(/</g, '&lt;').replace(/>/g, '&gt;'),
    ),
  )
}

export function stabilizeForStream(content: string): string {
  let next = content
  const fences = next.match(/```/g)?.length ?? 0
  if (fences % 2 === 1) next += '\n```'
  const display = next.match(/\$\$/g)?.length ?? 0
  if (display % 2 === 1) next += '\n$$'
  return next
}

export function prepareAssistantMarkdown(content: string): string {
  if (!content) return ''
  return stabilizeForStream(
    escapeLiteralHtml(escapeCurrencyDollars(convertLatexDelimiters(content))),
  )
}

export function markdownUrlTransform(
  url: string,
  key?: string,
  node?: { tagName?: string },
): string {
  if (
    key === 'src' &&
    String(node?.tagName || '').toLowerCase() === 'img' &&
    SAFE_RASTER_DATA_RE.test(url)
  ) {
    return url
  }
  if (url.startsWith('#') || url.startsWith('/') || url.startsWith('.')) {
    return url
  }
  const colon = url.indexOf(':')
  if (colon === -1) return url
  const protocol = url.slice(0, colon)
  return SAFE_PROTOCOL_RE.test(protocol) ? url : ''
}
