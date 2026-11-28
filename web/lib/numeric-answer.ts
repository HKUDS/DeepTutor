/**
 * Deterministic numeric answer equivalence, ported from
 * `numeric_equivalent` in deeptutor/learning/grading.py (see its docstring
 * for the separator, precision, percent and unit rules). Values are exact
 * rationals like Python's Fraction, and both implementations run against
 * tests/fixtures/numeric_answers.json so they cannot drift.
 */

type Mark = '.' | ','
/** Exact rational: numerator, positive denominator. */
type Q = [n: bigint, d: bigint]
type Reading = [value: Q, decimals: number | null]
type Outcome = boolean | 'rounded' | null

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
  /** Matches under another reading only; neither a final "right" nor "wrong". */
  ambiguous: boolean
  parts: NumericPart[]
}

const FOLD = /[\u2212\u2013\u00a0\u202f\u2009\u2019]/g
const FOLDED: Record<string, string> = { '\u2212': '-', '\u2013': '-', '\u2019': "'" }
const LABEL =
  /(?<![^\s,;])\s*(?:\(?([a-z]{1,3}|[0-9]{1,2})\)|(\p{L}[\p{L}\p{N}_'[\]]{0,15})\s*[=:])/giu
const NUMBER =
  /^([^0-9]*?)([0-9](?:[0-9.,' ]*[0-9])?)(?:\s*\/\s*([0-9]{1,15})|[eE]([+-]?[0-9]{1,2}))?([\s\S]*)$/
const PREFIX = /^(?:≈|~|ca\.?|approx\.?)?\s*[+-]?\s*(?:€|\$|£|eur|usd|gbp|chf)?\s*[+-]?$/i
const UNIT = /^\p{L}+\.?(?:\/\p{L}+)?$/u
const CURRENCY = new Map(
  Object.entries({ '€': 'eur', euro: 'eur', $: 'usd', '£': 'gbp', eur: 'eur', usd: 'usd' })
)
CURRENCY.set('gbp', 'gbp').set('chf', 'chf')
// Words that change the magnitude or meaning and so may never be dropped.
const FIXED_UNITS = new Set(
  (
    'tsd teur mio mrd bn pi dozen dutzend hundred hundert thousand tausend ' +
    'million millionen milliarde milliarden billion billionen'
  ).split(' ')
)
const MAX_DIGITS = 30
const OTHER: Record<Mark, Mark> = { '.': ',', ',': '.' }
const isMark = (s: string | null | undefined): s is Mark => s === '.' || s === ','
const pow10 = (e: number) => 10n ** BigInt(e)
const scale = ([n, d]: Q, num: bigint, den = 1n): Q => [n * num, d * den]
const sub = ([a, b]: Q, [c, d]: Q): Q => [a * d - c * b, b * d]
const abs = ([n, d]: Q): Q => [n < 0n ? -n : n, d]
const cmp = ([a, b]: Q, [c, d]: Q) => (a * d > c * b ? 1 : a * d < c * b ? -1 : 0)

function value(groups: string[], frac: string): [Q, number] {
  if (groups.length > 1 && !(groups[0].length <= 3 && groups.slice(1).every(g => g.length === 3))) {
    throw new Error('invalid digit grouping')
  }
  if (groups.join('').length + frac.length > MAX_DIGITS)
    throw new Error('not an answer-sized number')
  return [[BigInt(groups.join('') + frac), pow10(frac.length)], frac.length]
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
    if (BigInt(den) === 0n) return null
    step = ([v]) => [scale(v, 1n, BigInt(den)), null]
  }
  if (exp !== undefined) {
    const e = Number(exp)
    step = ([v, d]) => [
      e >= 0 ? scale(v, pow10(e)) : scale(v, 1n, pow10(-e)),
      d === null ? null : Math.max(0, d - e),
    ]
  }
  const sign = pre.includes('-') ? -1n : 1n
  const scaled = (r: Reading): Reading => {
    const [v, d] = step(r)
    return [scale(v, sign, percent ? 100n : 1n), d]
  }
  return {
    readings: { '.': scaled(initial['.']), ',': scaled(initial[',']) },
    implied,
    percent,
    currency: [...currencies].join(''),
    unit: units.join('').replace(/\.$/, ''), // "Mio." is "Mio"
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

/** Whether `v` rounded half away from zero to `decimals` places is `target`. */
function roundsTo(v: Q, target: Q, decimals: number): boolean {
  const order = cmp(abs(sub(v, target)), [1n, 2n * pow10(decimals)])
  return order < 0 || (order === 0 && cmp(abs(v), abs(target)) < 0)
}

const shift = (decimals: number | null, by: number) =>
  decimals === null ? null : Math.max(0, decimals + by)

function close(v: Q, key: Q, decimals: number | null, keyDecimals: number | null): Outcome {
  if (cmp(v, key) === 0) return true
  // A key with two or more places accepts answers that round to it; a
  // fraction key must round to the answer's two or more places ("0,13" for 1/8).
  if (keyDecimals === null) {
    if (decimals !== null && decimals >= 2 && roundsTo(key, v, decimals)) return true
  } else if (keyDecimals >= 2 && roundsTo(v, key, keyDecimals)) return true
  // "3,48" for "3,4833": the question may ask for two decimals. A key with
  // fewer than two places ("12.5" stored from 12.50, "417") cannot settle a
  // finer answer that rounds to it.
  const coarser = decimals !== null && (keyDecimals === null || decimals < keyDecimals)
  const finer = decimals !== null && keyDecimals !== null && decimals > keyDecimals
  if ((coarser && roundsTo(key, v, decimals)) || (finer && roundsTo(v, key, keyDecimals))) {
    return 'rounded'
  }
  // "1250" for "-1250": the question may ask for the amount of a loss.
  const negated: Q = [-v[0], v[1]]
  if (v[0] !== 0n && v[0] < 0n !== key[0] < 0n && close(negated, key, decimals, keyDecimals)) {
    return 'rounded'
  }
  return false
}

function matches(given: NumberToken, key: NumberToken, markGiven: Mark, markKey: Mark): Outcome {
  const lone = given.unit || key.unit
  if (
    (given.currency && key.currency && given.currency !== key.currency) ||
    (given.unit !== key.unit &&
      ((given.unit && key.unit) ||
        lone.length < 2 ||
        FIXED_UNITS.has(lone) ||
        given.currency ||
        key.currency))
  ) {
    return null
  }
  const [keyValue, keyDecimals] = key.readings[markKey]
  const [v, decimals] = given.readings[markGiven]
  // Compare in the key's written units; a bare "12.5" answers a "12.5%" key.
  const k = key.percent ? 100n : 1n
  const shifted = shift(decimals, (given.percent ? 2 : 0) - (key.percent ? 2 : 0))
  const outcome = close(scale(v, k), scale(keyValue, k), shifted, keyDecimals)
  if (outcome !== false) return outcome
  if (key.percent && !given.percent) {
    const bare = close(v, scale(keyValue, k), decimals, keyDecimals)
    // "0.5" for "0.5%" may also be the rate written as a fraction (50 %).
    return bare && cmp(abs(v), [1n, 1n]) < 0 ? 'rounded' : bare
  }
  if (given.percent && !key.percent && close(scale(v, 100n), keyValue, decimals, keyDecimals)) {
    return null // "50%" for "50" may be right; leave it to the caller
  }
  // "42" for "0,42" (or the reverse) may be the same rate in percent points.
  const rate = (q: Q) => q[0] !== 0n && cmp(abs(q), [1n, 1n]) < 0
  if (
    !given.percent &&
    !key.percent &&
    ((rate(keyValue) && close(v, scale(keyValue, 100n), decimals, shift(keyDecimals, -2))) ||
      (rate(v) && close(scale(v, 100n), keyValue, shift(decimals, -2), keyDecimals)))
  ) {
    return 'rounded'
  }
  // "1.250.000" for "1.250": the question may state the key in TEUR or Mio.
  if (
    !(given.percent || key.percent || given.unit || key.unit) &&
    v[0] !== 0n &&
    [1, 2, 3].some(
      e =>
        cmp(v, scale(keyValue, pow10(3 * e))) === 0 || cmp(keyValue, scale(v, pow10(3 * e))) === 0
    )
  ) {
    return 'rounded'
  }
  return false
}

/**
 * Decisive [given, key] decimal marks, then every other reading. Only the
 * key's own notation fixes how the key is read; the answer borrows the key's
 * convention, never the reverse.
 */
function conventions(given: NumberToken[], keys: NumberToken[]): [number, [Mark, Mark][]] {
  const ownGiven = convention(given)
  const ownKey = convention(keys)
  const marksGiven: Mark[] = ownGiven ? [ownGiven] : ['.', ',']
  const marksKey: Mark[] = ownKey ? [ownKey] : ['.', ',']
  const options: [Mark, Mark][] = marksKey.map(k => [ownGiven ?? k, k])
  const decisive = options.length
  for (const g of marksGiven) {
    for (const k of marksKey) {
      if (!options.some(([og, ok]) => og === g && ok === k)) options.push([g, k])
    }
  }
  return [decisive, options]
}

export function numericEquivalent(userAnswer: string, expectedAnswer: string): NumericResult {
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
  const [decisive, marks] = conventions(
    pairs.map(p => p.given),
    pairs.map(p => p.key)
  )
  const outcomes: Outcome[][] = []
  for (const [mg, mk] of marks) {
    const outcome = pairs.map(p => matches(p.given, p.key, mg, mk))
    if (outcome.includes(null)) return none
    outcomes.push(outcome)
  }
  const partOk = pairs.map((_, i) => outcomes.slice(0, decisive).every(o => o[i] === true))
  const correct = partOk.every(Boolean)
  return {
    comparable: true,
    correct,
    ambiguous: !correct && outcomes.some(o => o.every(Boolean)),
    parts: pairs.map((p, i) => ({
      label: p.label,
      expected: p.key.text,
      given: p.given.text,
      correct: partOk[i],
    })),
  }
}
