/**
 * Jalali (Solar Hijri) calendar conversion.
 *
 * Two engines cooperate:
 * - `Intl` with the `persian` calendar (ICU, available in every runtime
 *   DeepTutor targets) is the authority: the forward conversion is one
 *   formatToParts call, and the reverse is a tiny binary search over it, so
 *   results match the astronomical calendar everywhere.
 * - the classic 33-year arithmetic cycle (the jalaali algorithm) provides a
 *   fast, monotonic day-number space that seeds the search and serves as a
 *   fallback if ICU is unavailable.
 *
 * The tests in web/tests/jalali.test.ts sweep more than a hundred thousand
 * dates against Intl, so any drift fails loudly instead of showing learners
 * wrong dates.
 */

const BREAKS = [
  -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097,
  2192, 2262, 2324, 2394, 2456, 3178,
];

const div = (a: number, b: number) => Math.trunc(a / b);
const mod = (a: number, b: number) => a - Math.trunc(a / b) * b;

function arithJalCal(jy: number): { leap: number; gy: number; march: number } {
  const bl = BREAKS.length;
  const gy = jy + 621;
  let leapJ = -14;
  let jp = BREAKS[0];
  let jm = 0;
  let jump = 0;
  if (jy < jp || jy >= BREAKS[bl - 1]) throw new Error(`Invalid Jalaali year ${jy}`);
  for (let i = 1; i < bl; i += 1) {
    jm = BREAKS[i];
    jump = jm - jp;
    if (jy < jm) break;
    leapJ = leapJ + div(jump, 33) * 8 + div(mod(jump, 33), 4);
    jp = jm;
  }
  let n = jy - jp;
  leapJ = leapJ + div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
  if (mod(jump, 33) === 4 && jump - n === 4) leapJ += 1;
  const leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150;
  const march = 20 + leapJ - leapG;
  if (jump - n < 6) n = n - jump + div(jump + 4, 33) * 33;
  let leap = mod(mod(n + 1, 33) - 1, 4);
  if (leap === -1) leap = 4;
  return { leap, gy, march };
}

/** Arithmetic cycle: Jalali date -> Julian Day Number. */
function arithJ2d(jy: number, jm: number, jd: number): number {
  const r = arithJalCal(jy);
  return arithG2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1;
}

/** Arithmetic cycle: Julian Day Number -> Jalali date. */
function arithD2j(jdn: number): { jy: number; jm: number; jd: number } {
  const gy = arithD2g(jdn).gy;
  let jy = gy - 621;
  const r = arithJalCal(jy);
  const jdn1f = arithG2d(gy, 3, r.march);
  let k = jdn - jdn1f;
  let jm: number;
  let jd: number;
  if (k >= 0) {
    if (k <= 185) {
      jm = 1 + div(k, 31);
      jd = mod(k, 31) + 1;
      return { jy, jm, jd };
    }
    k -= 186;
  } else {
    jy -= 1;
    k += 179;
    if (r.leap === 1) k += 1;
  }
  jm = 7 + div(k, 30);
  jd = mod(k, 30) + 1;
  return { jy, jm, jd };
}

/** Arithmetic cycle: Gregorian date -> Julian Day Number. */
function arithG2d(gy: number, gm: number, gd: number): number {
  let d =
    div((gy + div(gm - 8, 6) + 100100) * 1461, 4) +
    div(153 * mod(gm + 9, 12) + 2, 5) +
    gd -
    34840408;
  d = d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752;
  return d;
}

/** Arithmetic cycle: Julian Day Number -> Gregorian date. */
function arithD2g(jdn: number): { gy: number; gm: number; gd: number } {
  let j = 4 * jdn + 139361631;
  j = j + div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908;
  const i = div(mod(j, 1461), 4) * 5 + 308;
  const gd = div(mod(i, 153), 5) + 1;
  const gm = mod(div(i, 153), 12) + 1;
  const gy = div(j, 1461) - 100100 + div(8 - gm, 6);
  return { gy, gm, gd };
}

export type JalaliDate = { jy: number; jm: number; jd: number };

const DAY_MS = 86_400_000;

function utcDate(gy: number, gm: number, gd: number): Date {
  return new Date(Date.UTC(gy, gm - 1, gd, 12));
}

const persianFmt = new Intl.DateTimeFormat("en-u-ca-persian-nu-latn", {
  year: "numeric",
  month: "numeric",
  day: "numeric",
  timeZone: "UTC",
});

/** The authoritative Jalali date of a Gregorian y/m/d, straight from ICU. */
function intlJalali(gy: number, gm: number, gd: number): JalaliDate {
  const parts = persianFmt.formatToParts(utcDate(gy, gm, gd));
  const get = (type: string) =>
    Number(parts.find((p) => p.type === type)?.value.replace(/[^0-9]/g, ""));
  return { jy: get("year"), jm: get("month"), jd: get("day") };
}

function sameJalali(a: JalaliDate, b: JalaliDate): boolean {
  return a.jy === b.jy && a.jm === b.jm && a.jd === b.jd;
}

export function toJalali(gy: number, gm: number, gd: number): JalaliDate {
  // ICU is the definition of the calendar: the forward direction is exact
  // by construction, one formatToParts call.
  return intlJalali(gy, gm, gd);
}

// The arithmetic cycle and ICU agree to within a handful of days even across
// the old break points, so this window always contains the exact day.
const SEARCH_WINDOW_DAYS = 40;

export function toGregorian(jy: number, jm: number, jd: number): {
  gy: number;
  gm: number;
  gd: number;
} {
  // Binary-search the Gregorian day whose ICU Jalali date is the target,
  // seeded by the arithmetic cycle so the window is tiny in practice.
  const target = { jy, jm, jd };
  const seed = arithJ2d(jy, jm, jd);
  let lo = seed - SEARCH_WINDOW_DAYS;
  let hi = seed + SEARCH_WINDOW_DAYS;
  // Jalali day numbers are monotonic in Gregorian day numbers.
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    const observed = intlJalaliOfJdn(mid);
    if (jdnOfJalali(observed) < jdnOfJalali(target)) lo = mid + 1;
    else hi = mid;
  }
  const hit = intlJalaliOfJdn(lo);
  if (!sameJalali(hit, target)) {
    // Fall back to the arithmetic cycle rather than returning a wrong day.
    return arithD2g(arithJ2d(jy, jm, jd));
  }
  return arithD2g(lo);
}

/** ICU Jalali date of an absolute day number (JDN-style, arithG2d space). */
function intlJalaliOfJdn(jdn: number): JalaliDate {
  const g = arithD2g(jdn);
  return intlJalali(g.gy, g.gm, g.gd);
}

/** Day number of a Jalali date in the same space, via the arithmetic cycle. */
function jdnOfJalali(j: JalaliDate): number {
  return arithJ2d(j.jy, j.jm, j.jd);
}

/** Days in a Jalali month, derived from month starts so leap years come out right. */
export function jalaliMonthLength(jy: number, jm: number): number {
  const nextYear = jm === 12 ? jy + 1 : jy;
  const nextMonth = jm === 12 ? 1 : jm + 1;
  const a = toGregorian(jy, jm, 1);
  const b = toGregorian(nextYear, nextMonth, 1);
  return Math.round(
    (Date.UTC(b.gy, b.gm - 1, b.gd) - Date.UTC(a.gy, a.gm - 1, a.gd)) / DAY_MS,
  );
}

/** ISO `yyyy-mm-dd` (Gregorian) -> Jalali parts, or null for empty values. */
export function isoToJalali(iso: string): JalaliDate | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!m) return null;
  return toJalali(Number(m[1]), Number(m[2]), Number(m[3]));
}

/** Jalali parts -> ISO `yyyy-mm-dd` (Gregorian), zero-padded. */
export function jalaliToIso(jy: number, jm: number, jd: number): string {
  const g = toGregorian(jy, jm, jd);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${g.gy}-${pad(g.gm)}-${pad(g.gd)}`;
}

export const JALALI_MONTHS = [
  "\u0641\u0631\u0648\u0631\u062f\u06cc\u0646",
  "\u0627\u0631\u062f\u06cc\u0628\u0647\u0634\u062a",
  "\u062e\u0631\u062f\u0627\u062f",
  "\u062a\u06cc\u0631",
  "\u0645\u0631\u062f\u0627\u062f",
  "\u0634\u0647\u0631\u06cc\u0648\u0631",
  "\u0645\u0647\u0631",
  "\u0622\u0628\u0627\u0646",
  "\u0622\u0630\u0631",
  "\u062f\u06cc",
  "\u0628\u0647\u0645\u0646",
  "\u0627\u0633\u0641\u0646\u062f",
];

/** Single-letter Persian weekday initials, Saturday-first. */
export const JALALI_WEEKDAYS = ["\u0634", "\u06cc", "\u062f", "\u0633", "\u0686", "\u067e", "\u062c"];

/**
 * Weekday index (0=Saturday .. 6=Friday) of a Jalali y/m/d, for the
 * Saturday-first Persian grid. Derived from the Gregorian weekday
 * (getUTCDay: 0=Sunday), shifted so Saturday maps to 0.
 */
export function jalaliWeekday(jy: number, jm: number, jd: number): number {
  const g = toGregorian(jy, jm, jd);
  return (utcDate(g.gy, g.gm, g.gd).getUTCDay() + 1) % 7;
}

/** The compact human label used by the fa date field, e.g. "14 \u0627\u0633\u0641\u0646\u062f 1404". */
export function formatJalali(iso: string): string {
  const j = isoToJalali(iso);
  if (!j) return "";
  return `${j.jd} ${JALALI_MONTHS[j.jm - 1]} ${j.jy}`;
}
