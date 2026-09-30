import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { useWatching } from "../context/WatchingContext";

function WatchingProbe() {
  const watching = useWatching();
  return createElement(
    "p",
    null,
    `active:${watching.active ? "yes" : "no"} material:${watching.material ? "yes" : "no"}`,
  );
}

test("useWatching is safe outside WatchingProvider", () => {
  assert.equal(
    renderToStaticMarkup(createElement(WatchingProbe)),
    "<p>active:no material:no</p>",
  );
});
