import assert from "node:assert/strict";
import test from "node:test";
import i18next from "i18next";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { initReactI18next } from "react-i18next";

import MasteryStudyLayout from "../app/(utility)/mastery/[pathId]/study/layout";
import { useReading } from "../context/ReadingContext";
import { useWatching } from "../context/WatchingContext";

function ContextProbe() {
  const reading = useReading();
  const watching = useWatching();

  return createElement(
    "p",
    null,
    `reading:${reading.loading ? "loading" : "idle"} watching:${watching.active ? "active" : "idle"}`,
  );
}

test("the mastery study layout provides reading and watching contexts", async () => {
  await i18next.use(initReactI18next).init({
    lng: "en",
    fallbackLng: false,
    resources: { en: { translation: {} } },
  });
  assert.equal(
    renderToStaticMarkup(
      createElement(MasteryStudyLayout, null, createElement(ContextProbe)),
    ),
    "<p>reading:idle watching:idle</p>",
  );
});
