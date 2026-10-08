import test from "node:test";
import assert from "node:assert/strict";

import { getDayGroupKey } from "../lib/relative-time";

test("session day groups count local dates across spring daylight saving", (t) => {
  const previousTimezone = process.env.TZ;
  process.env.TZ = "America/New_York";
  t.after(() => {
    if (previousTimezone === undefined) delete process.env.TZ;
    else process.env.TZ = previousTimezone;
  });
  t.mock.timers.enable({ apis: ["Date"], now: new Date("2026-03-09T12:00:00-04:00") });

  assert.equal(getDayGroupKey(new Date("2026-03-08T12:00:00-04:00").getTime() / 1000), "yesterday");
});

test("seven calendar days remain outside the last-seven-days group across DST", (t) => {
  const previousTimezone = process.env.TZ;
  process.env.TZ = "America/New_York";
  t.after(() => {
    if (previousTimezone === undefined) delete process.env.TZ;
    else process.env.TZ = previousTimezone;
  });
  t.mock.timers.enable({ apis: ["Date"], now: new Date("2026-03-09T12:00:00-04:00") });

  assert.equal(getDayGroupKey(new Date("2026-03-02T12:00:00-05:00").getTime() / 1000), "earlier");
  assert.equal(getDayGroupKey(new Date("2026-03-03T12:00:00-05:00").getTime() / 1000), "last_7_days");
  assert.equal(getDayGroupKey(new Date("2026-03-09T01:00:00-04:00").getTime() / 1000), "today");
});
