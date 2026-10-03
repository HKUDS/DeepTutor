import test from "node:test";
import assert from "node:assert/strict";
import {
  escapeUnknownHtmlTagsForDisplay,
  markdownUrlTransform,
  normalizeMarkdownForDisplay,
  repairMalformedStrongEmphasis,
  safeDecodeURIComponent,
} from "../../lib/markdown-display";

// Security contract: after escaping, anything an HTML parser would treat as
// an active tag, event handler, or srcdoc must live only inside inline-code
// spans (which render inert). Assertions inspect the text OUTSIDE code spans.
function outsideCodeSpans(value: string): string {
  return value.replace(/`[^`\n]*`/g, "");
}

function assertInertAgainstHtml(output: string): void {
  const outside = outsideCodeSpans(output);
  assert.doesNotMatch(
    outside,
    /<\s*\/?\s*(?:script|iframe|object|embed|svg|style|link|base|form|meta)\b/i,
    `active tag survived outside code spans: ${JSON.stringify(output)}`,
  );
  assert.doesNotMatch(
    outside,
    /\bon[a-z]+\s*=/i,
    `event handler survived outside code spans: ${JSON.stringify(output)}`,
  );
  assert.doesNotMatch(
    outside,
    /\bsrcdoc\s*=/i,
    `srcdoc attribute survived outside code spans: ${JSON.stringify(output)}`,
  );
}

test("escapeUnknownHtmlTagsForDisplay renders script fixtures inert", () => {
  const fixtures = [
    "<script>alert(1)</script>",
    "<ScRiPt>alert(1)</sCrIpT>",
    '<script src="https://evil.example/x.js"></script>',
    "<script >alert(1)</script >",
    '<SCRIPT/SRC="https://evil.example/x.js">',
  ];
  for (const fixture of fixtures) {
    const output = escapeUnknownHtmlTagsForDisplay(fixture);
    assertInertAgainstHtml(output);
    assert.notEqual(output, fixture);
  }
});

test("escapeUnknownHtmlTagsForDisplay renders iframe, object, embed, and svg fixtures inert", () => {
  const fixtures = [
    '<iframe src="https://evil.example/frame"></iframe>',
    "<iframe></iframe>",
    '<object data="https://evil.example/x.swf"></object>',
    '<embed src="https://evil.example/x.swf">',
    "<svg><script>alert(1)</script></svg>",
  ];
  for (const fixture of fixtures) {
    const output = escapeUnknownHtmlTagsForDisplay(fixture);
    assertInertAgainstHtml(output);
    assert.notEqual(output, fixture);
  }
});

// Fails on origin/main: HTML_LIKE_TAG_REGEX stops at the first '>' even when
// it sits inside a quoted attribute value, so the iframe opening tag is never
// escaped and an HTML-compliant parser (rehype-raw/parse5) still reads it as
// a live element carrying srcdoc.
test("escapeUnknownHtmlTagsForDisplay escapes an iframe whose srcdoc value contains markup", () => {
  const fixture = '<iframe srcdoc="<script>alert(1)</script>"></iframe>';
  const output = escapeUnknownHtmlTagsForDisplay(fixture);
  assertInertAgainstHtml(output);
});

// Fails on origin/main: same quoted-'>' split — the tag match ends inside the
// attribute value, so the handler that follows it is never sanitized, while
// parse5 reassembles it into one live tag.
test("escapeUnknownHtmlTagsForDisplay sanitizes handlers hidden behind a quoted '>'", () => {
  const fixtures = [
    '<a title="a>b" onclick="alert(1)">link</a>',
    '<img src="x>y" onerror="alert(1)" alt="photo">',
    '<details open ontoggle="a>b" data-x="1">body</details>',
  ];
  for (const fixture of fixtures) {
    const output = escapeUnknownHtmlTagsForDisplay(fixture);
    assertInertAgainstHtml(output);
  }
});

// Fails on origin/main via the same quoted-'>' gap: percent decoding is fine,
// but the decoded markup must still be rendered inert by the escaper.
test("escapeUnknownHtmlTagsForDisplay keeps decoded percent-encoded markup inert", () => {
  const decoded = safeDecodeURIComponent(
    "%3Ca%20title%3D%22a%3Eb%22%20onclick%3D%22alert%281%29%22%3Elink%3C%2Fa%3E",
  );
  assert.equal(decoded, '<a title="a>b" onclick="alert(1)">link</a>');
  assertInertAgainstHtml(escapeUnknownHtmlTagsForDisplay(decoded));
});

test("safeDecodeURIComponent never throws and always returns a string", () => {
  const fixtures = ["%E0%A4%A", "%", "%25", "%%%", "%ZZ", "a%2", "%3Cscript%3E", ""];
  for (const fixture of fixtures) {
    let result: string | undefined;
    assert.doesNotThrow(() => {
      result = safeDecodeURIComponent(fixture);
    });
    assert.equal(typeof result, "string");
  }
});

test("double percent-decoding cannot smuggle live script markup through the display pipeline", () => {
  const doubleEncoded = "%253Cscript%253Ealert(1)%253C%252Fscript%253E";
  const once = safeDecodeURIComponent(doubleEncoded);
  assert.equal(once, "%3Cscript%3Ealert(1)%3C%2Fscript%3E");
  const twice = safeDecodeURIComponent(once);
  assert.equal(twice, "<script>alert(1)</script>");
  const displayed = escapeUnknownHtmlTagsForDisplay(twice);
  assert.notEqual(displayed, twice);
  assertInertAgainstHtml(displayed);
  assertInertAgainstHtml(escapeUnknownHtmlTagsForDisplay(once));
});

test("normalizeMarkdownForDisplay never percent-decodes markup", () => {
  const encoded = "text %3Cscript%3Ealert(1)%3C%2Fscript%3E end";
  const output = normalizeMarkdownForDisplay(encoded);
  assert.equal(output, encoded);
  assert.doesNotMatch(output, /<script/i);
});

// Invariant: repairing a malformed label may move whitespace across the
// closing marker but must not change the visible text (emphasis markers
// stripped) or the number of ** markers.
function emphasisPlainText(value: string): string {
  return value.split("**").join("");
}

test("repairMalformedStrongEmphasis keeps plain text identical before and after repair", () => {
  const fixtures = [
    "**Date: **2026",
    "**發布日期： **2026 年 7 月 30 日",
    "**A: **B**C: **D",
    "**Note: **value **with** bold",
    // Failing on origin/main: whitespace inside the closing marker is
    // rewritten to a single space instead of being preserved outside it.
    "**A:  **b",
    "**Label:\t**value",
    "**Time:  **now **Ref:\t**1",
  ];
  for (const fixture of fixtures) {
    const repaired = repairMalformedStrongEmphasis(fixture);
    assert.equal(
      emphasisPlainText(repaired),
      emphasisPlainText(fixture),
      `repair changed visible text: ${JSON.stringify(fixture)} -> ${JSON.stringify(repaired)}`,
    );
    assert.equal(
      repaired.split("**").length - 1,
      fixture.split("**").length - 1,
      `repair changed the number of ** markers: ${JSON.stringify(fixture)} -> ${JSON.stringify(repaired)}`,
    );
  }
});

test("repairMalformedStrongEmphasis keeps valid, unpaired, and protected lines byte-identical", () => {
  const fixtures = [
    "**Note: **Important**",
    "In Markdown, use ** to make text **bold**.",
    "**發布日期：** 2026 年 7 月 30 日",
    "**Label: **",
    "`**label: **value`",
    "```md\n**label: **value\n```",
    "$\\text{**label: **value}$",
    "Example:\n\n    **label: **value",
    "",
    "no markers at all",
  ];
  for (const fixture of fixtures) {
    assert.equal(repairMalformedStrongEmphasis(fixture), fixture);
  }
});

test("allowed tags lose event handlers, style, and unsafe URLs", () => {
  const fixtures: Array<[string, RegExp]> = [
    [
      '<a href="javascript:alert(1)" onclick="alert(2)" style="color:red">link</a>',
      /onclick|javascript:|style=/i,
    ],
    ['<details open ontoggle="alert(1)" onmouseover="alert(3)">x</details>', /on[a-z]+=/i],
    ['<img src="https://ok.example/a.png" onerror="alert(1)">', /onerror=/i],
  ];
  for (const [fixture, pattern] of fixtures) {
    const output = escapeUnknownHtmlTagsForDisplay(fixture);
    assert.doesNotMatch(output, pattern);
    assertInertAgainstHtml(output);
  }
});

test("markdownUrlTransform neutralizes active URL schemes including obfuscation", () => {
  const blocked = [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "java\tscript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
    "vbscript:msgbox(1)",
  ];
  for (const value of blocked) {
    assert.equal(markdownUrlTransform(value, "href", { tagName: "a" }), "");
  }
  assert.equal(
    markdownUrlTransform("https://example.com/page", "href", { tagName: "a" }),
    "https://example.com/page",
  );
  assert.equal(
    markdownUrlTransform("data:image/png;base64,iVBORw0KGgo=", "src", {
      tagName: "img",
    }),
    "data:image/png;base64,iVBORw0KGgo=",
  );
});
