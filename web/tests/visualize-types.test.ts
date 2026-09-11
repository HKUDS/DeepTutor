import assert from "node:assert/strict";
import test from "node:test";

import { extractVisualizeResult, isManimResult } from "@/lib/visualize-types";

test("extracts a versioned plugin canvas envelope", () => {
  const result = extractVisualizeResult({
    schema_version: "deeptutor.visualization/v1",
    render_type: "geogebra",
    renderer: {
      id: "geogebra",
      version: "1.0.0",
      target: "native",
      native_renderer: "geogebra",
    },
    payload: {
      format: "application/vnd.geogebra.commands+json",
      data: { app_name: "geometry", commands: ["A=(0,0)", "B=(2,0)"] },
    },
    presentation: { title: "Segment AB", description: "Drag either point." },
  });

  assert.ok(result);
  assert.equal(isManimResult(result), false);
  if (isManimResult(result)) return;
  assert.equal(result.renderer.native_renderer, "geogebra");
  assert.deepEqual(result.payload.data, {
    app_name: "geometry",
    commands: ["A=(0,0)", "B=(2,0)"],
  });
  assert.match(result.code.content, /"commands"/);
});

test("keeps legacy SVG results renderable", () => {
  const result = extractVisualizeResult({
    render_type: "svg",
    code: { language: "svg", content: "<svg viewBox='0 0 10 10'></svg>" },
  });
  assert.ok(result && !isManimResult(result));
  if (!result || isManimResult(result)) return;
  assert.equal(result.renderer.native_renderer, "svg");
  assert.equal(result.payload.data, "<svg viewBox='0 0 10 10'></svg>");
});
