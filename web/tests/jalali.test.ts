import test from "node:test";
import assert from "node:assert/strict";

import {
  isoToJalali,
  jalaliMonthLength,
  jalaliToIso,
  jalaliWeekday,
  formatJalali,
  toGregorian,
  toJalali,
} from "../lib/jalali";

// Intl's `persian` calendar is the authority: the hand-rolled arithmetic must
// agree with it for every proleptic date, including leap years (Esfand 30).
const fmt = new Intl.DateTimeFormat("en-u-ca-persian-nu-latn", {
  year: "numeric",
  month: "numeric",
  day: "numeric",
  timeZone: "UTC",
});

function intlJalali(date: Date): { jy: number; jm: number; jd: number } {
  const parts = fmt.formatToParts(date);
  const get = (type: string) =>
    Number(parts.find((p) => p.type === type)?.value.replace(/[^0-9]/g, ""));
  // Intl may label the era "AH"; the numeric year is the Jalali year either way.
  return { jy: get("year"), jm: get("month"), jd: get("day") };
}

test("conversion matches Intl persian calendar across eleven centuries", () => {
  // Step through ~4,000 days spread over 1200..2500 CE, hitting leap years
  // and month boundaries on both calendars. The Intl correction keeps the
  // hybrid exact even where the bare 33-year cycle would drift.
  let t = Date.UTC(1200, 2, 21);
  const end = Date.UTC(2500, 0, 1);
  let checked = 0;
  while (t < end) {
    const date = new Date(t);
    const gy = date.getUTCFullYear();
    const gm = date.getUTCMonth() + 1;
    const gd = date.getUTCDate();
    const j = toJalali(gy, gm, gd);
    const expected = intlJalali(date);
    assert.deepEqual(
      { jy: j.jy, jm: j.jm, jd: j.jd },
      { jy: expected.jy, jm: expected.jm, jd: expected.jd },
      `${gy}-${gm}-${gd}`,
    );
    const back = toGregorian(j.jy, j.jm, j.jd);
    assert.deepEqual(back, { gy, gm, gd });
    t += 3 * 24 * 3600 * 1000 + 1;
    checked += 1;
  }
  assert.ok(checked > 150_000, `expected a dense sweep, checked ${checked}`);
});

test("round-trips and month lengths are consistent", () => {
  for (let jy = 1178; jy <= 1478; jy += 1) {
    let total = 0;
    for (let jm = 1; jm <= 12; jm += 1) {
      const len = jalaliMonthLength(jy, jm);
      assert.ok(len === 29 || len === 30 || len === 31, `${jy}/${jm} -> ${len}`);
      // First day of each month round-trips through Gregorian.
      const g = toGregorian(jy, jm, 1);
      const j = toJalali(g.gy, g.gm, g.gd);
      assert.deepEqual(j, { jy, jm, jd: 1 });
      total += len;
    }
    // A Jalali year is 365 or 366 days.
    assert.ok(total === 365 || total === 366, `${jy} has ${total} days`);
  }
});

test("weekday anchors: 1 Farvardin 1404 and today's grid alignment", () => {
  // 2025-03-21 was 1 Farvardin 1404, a Friday (ج = index 6).
  assert.equal(jalaliWeekday(1404, 1, 1), 6);
  assert.equal(jalaliToIso(1404, 1, 1), "2025-03-21");
});

test("ISO helpers format and parse", () => {
  assert.deepEqual(isoToJalali("2026-03-05"), { jy: 1404, jm: 12, jd: 14 });
  assert.equal(jalaliToIso(1404, 12, 14), "2026-03-05");
  // Display label: Persian digits, month before year.
  assert.equal(formatJalali("2026-03-05"), "\u06f1\u06f4 \u0627\u0633\u0641\u0646\u062f \u06f1\u06f4\u06f0\u06f4");
  assert.equal(formatJalali("2026-10-23"), "\u06f1 \u0622\u0628\u0627\u0646 \u06f1\u06f4\u06f0\u06f5");
  assert.equal(isoToJalali(""), null);
  assert.equal(isoToJalali("not-a-date"), null);
});
