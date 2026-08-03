import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const richRendererSource = readFileSync(
  path.join(process.cwd(), "components/common/RichMarkdownRenderer.tsx"),
  "utf8",
);
const simpleRendererSource = readFileSync(
  path.join(process.cwd(), "components/common/SimpleMarkdownRenderer.tsx"),
  "utf8",
);

test("rich-markdown-renderer: non-rich multiline fallback documents settings boundary", () => {
  assert.match(
    richRendererSource,
    /code-block appearance settings apply only when rich code rendering is enabled/i,
  );
});

test("simple-markdown-renderer: compatibility fallback documents settings boundary", () => {
  assert.match(simpleRendererSource, /compatibility fallback/i);
  assert.match(
    simpleRendererSource,
    /does not consume the[\s\S]*code-block theme registry/i,
  );
});

test("rich-markdown-renderer: enableCode=false keeps multiline code as static readable fallback", () => {
  assert.match(richRendererSource, /if \(isMultiline && enableCode\)/);
  assert.match(richRendererSource, /if \(isMultiline\)/);
  assert.match(richRendererSource, /bg-\[\#1f2937\]/);
  assert.match(richRendererSource, /text-\[\#e5e7eb\]/);
  assert.doesNotMatch(richRendererSource, /showLineNumbers=/);
  assert.doesNotMatch(richRendererSource, /wrapLongLines=/);
});

test("simple-markdown-renderer: multiline code remains a static compatibility block", () => {
  assert.match(simpleRendererSource, /raw\.includes\("\\n"\)/);
  assert.match(simpleRendererSource, /bg-\[\#1f2937\]/);
  assert.match(simpleRendererSource, /text-\[\#e5e7eb\]/);
  assert.doesNotMatch(simpleRendererSource, /code-block-themes/);
  assert.doesNotMatch(simpleRendererSource, /showLineNumbers=/);
  assert.doesNotMatch(simpleRendererSource, /wrapLongLines=/);
});
