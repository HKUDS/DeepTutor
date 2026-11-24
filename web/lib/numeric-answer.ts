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
  currency: string
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
  /** Correct only under a non-preferred separator reading; not a final "wrong". */
  ambiguous: boolean
  parts: NumericPart[]
}

const FOLD = /[\u2212\u2013\u00a0\u202f\u2009\u2019]/g
const FOLDED: Record<string, string> = { '\u2212': '-', '\u2013': '-', '\u2019': "'" }
const LABEL =
  /(?<![^\s,;])\s*(?:\(?([a-z]{1,3}|[0-9]{1,2})\)|(\p{L}[\p{L}\p{N}_'[\]]{0,15})\s*[=:])/giu
const NUMBER =
  /^([^0-9]*?)([0-9](?:[0-9.,' ]*[0-9])?)(?:\s*\/\s*([0-9]+)|[eE]([+-]?[0-9]{1,2}))?([\s\S]*)$/
const PREFIX = /^(?:≈|~|ca\.?|approx\.?)?\s*[+-]?\s*(?:€|\$|£|eur|usd|gbp|chf)?\s*[+-]?$/i
const UNIT = /^\p{L}+\.?(?:\/\p{L}+)?$/u
const CURRENCY = new Map(
  Object.entries({ '€': 'eur', euro: 'eur', $: 'usd', '£': 'gbp', eur: 'eur', usd: 'usd' })
)
CURRENCY.set('gbp', 'gbp').set('chf', 'chf')
// Words that change the magnitude or meaning and so may never be dropped.
const FIXED_UNITS = new Set(
  (
    'tsd tsd. teur mio mio. mrd mrd. bn pi dozen dutzend hundred hundert thousand tausend ' +
    'million millionen milliarde milliarden billion billionen'
  ).split(' ')
)
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
  const match = NUMBER.exec(text.replace(FOLD, c => FOLDED[c] ?? ' ').trim())
  if (!match || !PREFIX.test(match[1].trim())) return null
  const [, pre, num, den, exp, rawPost] = match
  // "--5"; "3x" is algebra, not a unit
  if ((pre.match(/[+-]/g) ?? []).length > 1 || /^\p{L}/u.test(rawPost)) return null
  let post = rawPost.trim()
  const percent =
    post.startsWith('%') || ['prozent', 'percent'].includes(post.toLowerCase().split(' ')[0])
  if (percent) {
    const space = post.indexOf(' ')
    post = post.startsWith('%') ? post.slice(1) : space < 0 ? '' : post.slice(space + 1)
  }
  const words = post.toLowerCase().replace(/€/g, ' € ').split(/\s+/).filter(Boolean)
  const currency = /[€$£]|eur|usd|gbp|chf/i.exec(pre)
  const currencies = new Set(words.flatMap(w => CURRENCY.get(w) ?? []))
  if (currency) currencies.add(CURRENCY.get(currency[0].toLowerCase())!)
  const units = words.filter(w => !CURRENCY.has(w))
  if (currencies.size > 1 || units.length > 1 || !units.every(w => UNIT.test(w))) {
    return null // prose such as "5 or six", or symbols such as "3²"
  }
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
    currency: [...currencies].join(''),
    unit: units.join(''),
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
  // Absolute like the Python port; the tiny relative term only absorbs float noise.
  const eps = 1e-9 + 4 * Number.EPSILON * Math.abs(v)
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
  const lone = given.unit || key.unit
  if (
    (given.currency && key.currency && given.currency !== key.currency) ||
    (given.unit !== key.unit &&
      ((given.unit && key.unit) || lone.length < 2 || FIXED_UNITS.has(lone)))
  ) {
    return null
  }
  let [keyValue, decimals] = key.readings[markKey]
  const [v, givenDecimals] = given.readings[markGiven]
  if (decimals === null && (givenDecimals ?? 0) >= 2) decimals = givenDecimals // "0.33" for "1/3"
  // Compare in the key's written units; "12.5" answers "12.5%" and "50%" answers "50".
  const scale = key.percent ? 100 : 1
  const candidates = [v * scale]
  if (key.percent !== given.percent) candidates.push(key.percent ? v : v * 100)
  const tol = tolerance(keyValue * scale, decimals, relTol, absTol)
  return candidates.some(c => Math.abs(c - keyValue * scale) <= tol)
}

/** Preferred [given, key] decimal marks first, then the other readings. */
function conventions(given: NumberToken[], keys: NumberToken[]): [boolean, [Mark, Mark][]] {
  const ownGiven = convention(given)
  const ownKey = convention(keys)
  const both: [Mark, Mark][] = [
    ['.', '.'],
    [',', ','],
  ]
  if (!ownGiven && !ownKey) return [false, both]
  const preferred: [Mark, Mark] = [(ownGiven ?? ownKey)!, (ownKey ?? ownGiven)!]
  const options: [Mark, Mark][] = [preferred]
  for (const g of ownGiven ? [ownGiven] : (['.', ','] as Mark[])) {
    for (const k of ownKey ? [ownKey] : (['.', ','] as Mark[])) {
      if (g !== preferred[0] || k !== preferred[1]) options.push([g, k])
    }
  }
  return [true, options]
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
  const givenLabels = new Set(given.map(([l]) => l))
  const labelled =
    !keyLabels.includes(null) && !givenLabels.has(null) && new Set(keyLabels).size === keys.length
  if (labelled && (givenLabels.size !== keys.length || !keyLabels.every(l => givenLabels.has(l)))) {
    return none
  }
  const byLabel = new Map(given)
  const pairs = keys.map(([label, key], i) => ({
    label: label ?? given[i][0],
    given: labelled ? byLabel.get(label)! : given[i][1],
    key,
  }))
  const [hasPreferred, marks] = conventions(
    pairs.map(p => p.given),
    pairs.map(p => p.key)
  )
  const outcomes: boolean[][] = []
  for (const [mg, mk] of marks) {
    const outcome = pairs.map(p => matches(p.given, p.key, mg, mk, options.relTol, options.absTol))
    if (outcome.includes(null)) return none
    outcomes.push(outcome as boolean[])
  }
  const allOk = (o: boolean[]) => o.every(Boolean)
  const correct = hasPreferred ? allOk(outcomes[0]) : outcomes.every(allOk)
  const partOk = hasPreferred ? outcomes[0] : pairs.map((_, i) => outcomes.every(o => o[i]))
  return {
    comparable: true,
    correct,
    ambiguous: !correct && outcomes.some(allOk),
    parts: pairs.map((p, i) => ({
      label: p.label,
      expected: p.key.text,
      given: p.given.text,
      correct: partOk[i],
    })),
  }
}
