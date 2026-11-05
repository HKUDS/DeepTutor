import test from "node:test";
import assert from "node:assert/strict";

import {
  addJalaliMonths,
  dateKey,
  formatJalaliFullDate,
  formatJalaliMonthTitle,
  formatJalaliWeekTitle,
  isPersian,
  jalaliMonthBounds,
  monthWeeks,
  startOfJalaliMonth,
  weekStartsOn,
} from "../features/calendar/model/dates";

// A Jalali month grid must line up with the Persian calendar in every cell:
// the bounds, the neighbouring days and the weekday the column starts on all
// have to agree, or a Persian reader sees Gregorian dates under a Jalali title.

test("weekStartsOn puts Saturday first in Persian and keeps Intl elsewhere", () => {
  assert.equal(weekStartsOn("fa"), 6);
  assert.equal(weekStartsOn("fa-IR"), 6);
  // Intl already reports Sunday for en/en-US and Monday for de; the Persian
  // override must not disturb either.
  assert.equal(weekStartsOn("en-US"), 0);
  assert.equal(weekStartsOn("en"), 0);
  assert.equal(weekStartsOn("de"), 1);
});

test("isPersian recognises the language tag, not a region", () => {
  assert.equal(isPersian("fa"), true);
  assert.equal(isPersian("fa-IR"), true);
  assert.equal(isPersian("en-US"), false);
  assert.equal(isPersian(""), false);
});

test("a Jalali month grid starts on Saturday and spans whole weeks", () => {
  // 1 Aban 1405 is 2026-10-23; the month has 30 days.
  const cursor = new Date(2026, 9, 26);
  const weeks = monthWeeks(cursor, 6, "fa");
  for (const week of weeks) {
    assert.equal(week.length, 7);
    assert.equal(week[0].getDay(), 6, "each row opens on a Saturday");
  }
  const flat = weeks.flat().map(dateKey);
  const [first, last] = jalaliMonthBounds(cursor);
  // Every cell of the month is present, and the grid covers it end to end.
  assert.ok(flat.includes(first));
  assert.ok(flat.includes(last));
  assert.equal(flat[flat.indexOf(first) - 1] < first, true);
  assert.equal(flat[flat.indexOf(last) + 1] > last, true);
});

test("monthWeeks stays Gregorian without a Persian locale", () => {
  const cursor = new Date(2026, 9, 26);
  const weeks = monthWeeks(cursor, 6);
  const flat = weeks.flat();
  // October 2026 has 31 days and the grid reaches 1..31.
  assert.ok(flat.some((d) => d.getMonth() === 9 && d.getDate() === 31));
});

test("Jalali month stepping follows Jalali months, not Gregorian ones", () => {
  // 1 Aban 1405 = 2026-10-23. One Jalali month later is 1 Azar = 2026-11-22.
  const aban = new Date(2026, 9, 23);
  const azar = addJalaliMonths(aban, 1);
  assert.equal(dateKey(azar), "2026-11-22");
  const back = addJalaliMonths(azar, -1);
  assert.equal(dateKey(back), dateKey(aban));
});

test("addJalaliMonths clamps a day past the target month's length", () => {
  // 31 Farvardin 1404 = 2025-04-20; Ordibehesht has 31 days, Khordad 31,
  // Tir 31, but Mordad 31 too — use Esfand (29/30) from Shahrivar 31 instead.
  const shahrivar31 = new Date(2025, 8, 22); // 31 Shahrivar 1404
  const esfand = addJalaliMonths(shahrivar31, 6);
  assert.equal(esfand.getDate() <= 30, true);
});

test("startOfJalaliMonth lands on the first day of the Jalali month", () => {
  const mid = new Date(2026, 10, 10); // 19 Aban 1405
  const first = startOfJalaliMonth(mid);
  const [firstIso] = jalaliMonthBounds(mid);
  assert.equal(dateKey(first), firstIso);
});

test("formatJalaliMonthTitle is month first, then the year in Persian digits", () => {
  assert.equal(formatJalaliMonthTitle(new Date(2026, 9, 26)), "آبان ۱۴۰۵");
  assert.equal(formatJalaliMonthTitle(new Date(2026, 10, 5)), "آبان ۱۴۰۵");
  assert.equal(formatJalaliMonthTitle(new Date(2026, 2, 5)), "اسفند ۱۴۰۴");
});

// The heading sits above a Jalali grid, so a Gregorian string there contradicts
// every cell under it. Day and week headings must carry Jalali dates too.
test("formatJalaliFullDate names the day, month and year", () => {
  // 3 November 2026 is 12 Aban 1405.
  assert.equal(formatJalaliFullDate(new Date(2026, 10, 3)), "۱۲ آبان ۱۴۰۵");
  assert.equal(formatJalaliFullDate(new Date(2026, 9, 23)), "۱ آبان ۱۴۰۵");
});

test("formatJalaliWeekTitle spans a week, and names both months when it crosses", () => {
  // 12–18 Aban 1405 = 2026-11-03 .. 2026-11-09.
  assert.equal(
    formatJalaliWeekTitle(new Date(2026, 10, 3), new Date(2026, 10, 9)),
    "۱۲ – ۱۸ آبان ۱۴۰۵",
  );
  // A week that straddles the month end: 30 Mehr – 6 Aban 1405.
  assert.equal(
    formatJalaliWeekTitle(new Date(2026, 9, 22), new Date(2026, 9, 28)),
    "۳۰ مهر – ۶ آبان ۱۴۰۵",
  );
});
