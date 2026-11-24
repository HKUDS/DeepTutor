/**
 * Deterministic numeric answer equivalence, ported from
 * `numeric_equivalent` in deeptutor/learning/grading.py (see its docstring
 * for the separator, tolerance, percent and unit rules). Both implementations
 * run against tests/fixtures/numeric_answers.json so they cannot drift.
 */

type Mark = '.' | ','
type Reading = [value: number, decimals: number | null]

interface NumberToken {
  readings: Record<Mark, Reading>
  implied: Mark | null
  percent: boolean
  unit: string
  text: string
}

export interface NumericPart {
  label: string | null
  expected: string
  given: string
  correct: boolean
}

export interface NumericResult {
  /** False when either side is not a plain numeric answer. */
  comparable: boolean
  correct: boolean
  /** The mismatch depends on an undecidable separator convention. */
  ambiguous: boolean
  parts: NumericPart[]
}

const FOLD: Record<string, string> = {
  '−': '-',
  '–': '-',
  ' ': ' ',
  ' ': ' ',
  ' ': ' ',
  '’': "'",
}
const LABEL =
  /(?<![^\s,;])\s*(?:\(?([a-z]{1,3}|\d{1,2})\)|(\p{L}[\p{L}\p{N}_'[\]]{0,15})\s*[=:])/giu
const NUMBER = /^([^\d]*?)(\d(?:[\d.,' ]*\d)?)(?:\s*\/\s*(\d+)|[eE]([+-]?\d+))?([\s\S]*)$/
const PREFIX = /^(?:≈|~|ca\.?|approx\.?)?\s*[+-]?\s*(?:€|\$|£|eur|usd|gbp|chf)?\s*[+-]?$/i
const CURRENCY: Record<string, string> = { '€': 'eur', euro: 'eur', $: 'usd', '£': 'gbp' }
const SCALE_WORDS = new Set([
  'k',
  't',
  'tsd',
  'tsd.',
  'teur',
  't€',
  'mio',
  'mio.',
  'mrd',
  'mrd.',
  'm',
  'bn',
  'thousand',
  'million',
  'millionen',
  'billion',
  'milliarden',
])
const OTHER: Record<Mark, Mark> = { '.': ',', ',': '.' }
const isMark = (s: string | null | undefined): s is Mark => s === '.' || s === ','

function value(groups: string[], frac: string): [number, number] {
  if (groups.length > 1 && !(groups[0].length <= 3 && groups.slice(1).every(g => g.length === 3))) {
    throw new Error('invalid digit grouping')
  }
  return [Number(`${groups.join('')}.${frac || '0'}`), frac.length]
}

function readings(raw: string): [Record<Mark, Reading>, Mark | null] {
  const seps = raw.match(/[.,' ]/g) ?? []
  const groups = raw.split(/[.,' ]/)
  const last = seps[seps.length - 1]
  if (isMark(last) && seps.filter(s => s === last).length === 1) {
    const head = groups[0]
    if (seps.length === 1 && groups[1].length === 3 && head.length <= 3 && head[0] !== '0') {
      // "125.000" / "1,250": decimal under one convention, grouping under the other.
      const both = {
        [last]: value(groups.slice(0, 1), groups[1]),
        [OTHER[last]]: value(groups, ''),
      }
      return [both as Record<Mark, Reading>, null]
    }
    if (new Set(seps.slice(0, -1)).size > 1) throw new Error('mixed grouping')
    const v = value(groups.slice(0, -1), groups[groups.length - 1])
    return [{ '.': v, ',': v }, last]
  }
  if (new Set(seps).size > 1) throw new Error('mixed separators')
  const v = value(groups, '')
  return [{ '.': v, ',': v }, isMark(seps[0]) ? OTHER[seps[0]] : null]
}

function parseNumber(text: string): NumberToken | null {
  const match = NUMBER.exec(text.replace(/[−–   ’]/g, c => FOLD[c]).trim())
  if (!match || !PREFIX.test(match[1].trim())) return null
  const [, pre, num, den, exp, rawPost] = match
  if (/^\p{L}/u.test(rawPost)) return null // "3x" is algebra, not a unit
  let post = rawPost.trim()
  const percent =
    post.startsWith('%') || ['prozent', 'percent'].includes(post.toLowerCase().split(' ')[0])
  if (percent) {
    const space = post.indexOf(' ')
    post = post.startsWith('%') ? post.slice(1) : space < 0 ? '' : post.slice(space + 1)
  }
  if (/[0-9]/.test(post) || post.length > 20) return null
  const currency = /[€$£]|eur|usd|gbp|chf/i.exec(pre)
  const words = post.toLowerCase().replace(/€/g, ' € ').split(/\s+/).filter(Boolean)
  if (currency) words.push(currency[0].toLowerCase())
  const unit = words
    .map(w => CURRENCY[w] ?? w)
    .sort()
    .join(' ')
  let parsed: [Record<Mark, Reading>, Mark | null]
  try {
    parsed = readings(num)
  } catch {
    return null
  }
  const [initial, implied] = parsed
  let step = (r: Reading): Reading => r
  if (den !== undefined) {
    if (Number(den) === 0) return null
    step = ([v]) => [v / Number(den), null]
  }
  if (exp !== undefined) {
    const e = Number(exp)
    step = ([v, d]) => [e >= 0 ? v * 10 ** e : v / 10 ** -e, d === null ? null : Math.max(0, d - e)]
  }
  const sign = pre.includes('-') ? -1 : 1
  const scaled = (r: Reading): Reading => {
    const [v, d] = step(r)
    return [(sign * v) / (percent ? 100 : 1), d]
  }
  return {
    readings: { '.': scaled(initial['.']), ',': scaled(initial[',']) },
    implied,
    percent,
    unit,
    text: text.trim(),
  }
}

function numericParts(text: string): [string | null, NumberToken][] | null {
  const parts: [string | null, NumberToken][] = []
  for (const chunk of String(text ?? '').split(/[;\n]+/)) {
    const labels = [...chunk.matchAll(LABEL)]
    if (labels.length && chunk.slice(0, labels[0].index).trim()) return null
    const bodies: [string | null, string][] = labels.length
      ? labels.map((m, i) => [
          (m[1] ?? m[2]).toLowerCase(),
          chunk.slice(m.index + m[0].length, labels[i + 1]?.index),
        ])
      : [[null, chunk]]
    for (const [label, raw] of bodies) {
      const body = raw.trim().replace(/,+$/, '').trim()
      if (!body && label === null) continue
      const number = parseNumber(body)
      if (!number) return null
      parts.push([label, number])
    }
  }
  return parts.length ? parts : null
}

function convention(numbers: NumberToken[]): Mark | null {
  const implied = new Set(numbers.map(n => n.implied).filter(isMark))
  return implied.size === 1 ? [...implied][0] : null
}

function tolerance(v: number, decimals: number | null, relTol?: number, absTol?: number): number {
  const eps = 1e-9 * Math.max(1, Math.abs(v))
  if (relTol !== undefined || absTol !== undefined) {
    return Math.max(absTol ?? 0, (relTol ?? 0) * Math.abs(v)) + eps
  }
  return (decimals ? 0.5 / 10 ** decimals : 0) + eps
}

function matches(
  given: NumberToken,
  key: NumberToken,
  markGiven: Mark,
  markKey: Mark,
  relTol?: number,
  absTol?: number
): boolean | null {
  const units = (given.unit || key.unit).split(' ')
  if (
    given.unit !== key.unit &&
    ((given.unit && key.unit) || units.some(w => SCALE_WORDS.has(w)))
  ) {
    return null
  }
  const [keyValue, decimals] = key.readings[markKey]
  const v = given.readings[markGiven][0]
  const scale = key.percent ? 100 : 1
  const candidates = [v * scale, ...(key.percent && !given.percent ? [v] : [])]
  const tol = tolerance(keyValue * scale, decimals, relTol, absTol)
  return candidates.some(c => Math.abs(c - keyValue * scale) <= tol)
}

export function numericEquivalent(
  userAnswer: string,
  expectedAnswer: string,
  options: { relTol?: number; absTol?: number } = {}
): NumericResult {
  const keys = numericParts(expectedAnswer)
  const given = numericParts(userAnswer)
  const none: NumericResult = { comparable: false, correct: false, ambiguous: false, parts: [] }
  if (!keys || !given) return none
  if (keys.length !== given.length) return { ...none, comparable: true }
  const keyLabels = keys.map(([l]) => l)
  const givenLabels = given.map(([l]) => l)
  const labelled =
    ![...keyLabels, ...givenLabels].includes(null) && new Set(keyLabels).size === keys.length
  if (
    labelled &&
    (new Set(givenLabels).size !== keyLabels.length ||
      !givenLabels.every(l => keyLabels.includes(l)))
  ) {
    return none
  }
  const byLabel = new Map(given)
  const pairs = keys.map(([label, key], i) => ({
    label: label ?? given[i][0],
    given: labelled ? byLabel.get(label)! : given[i][1],
    key,
  }))
  let markGiven = convention(pairs.map(p => p.given))
  let markKey = convention(pairs.map(p => p.key))
  ;[markGiven, markKey] = [markGiven ?? markKey, markKey ?? markGiven]
  const conventions: [Mark, Mark][] =
    markGiven && markKey
      ? [[markGiven, markKey]]
      : [
          ['.', '.'],
          [',', ','],
        ]
  const outcomes: boolean[][] = []
  for (const [mg, mk] of conventions) {
    const outcome = pairs.map(p => matches(p.given, p.key, mg, mk, options.relTol, options.absTol))
    if (outcome.includes(null)) return none
    outcomes.push(outcome as boolean[])
  }
  const partOk = pairs.map((_, i) => outcomes.every(o => o[i]))
  const ambiguous = new Set(outcomes.map(o => o.join())).size > 1
  return {
    comparable: true,
    correct: !ambiguous && partOk.every(Boolean),
    ambiguous,
    parts: pairs.map((p, i) => ({
      label: p.label,
      expected: p.key.text,
      given: p.given.text,
      correct: partOk[i],
    })),
  }
}
