import test from "node:test";
import assert from "node:assert/strict";

import { injectKaTeX, injectColorScheme, prepareIframeHtml } from "../lib/iframe-html";

function bridgeSource(): string {
  const prepared = prepareIframeHtml(
    "<!doctype html><html><head></head><body><main>content</main></body></html>",
  );
  const match = prepared.match(/<script data-dt-bridge>([\s\S]*?)<\/script>/);
  assert.ok(match, "prepared iframe HTML should contain the host bridge");
  return match[1];
}

test("iframe bridge measures current body content instead of historical viewport height", () => {
  const source = bridgeSource();

  assert.match(source, /body\.scrollHeight > 0/);
  assert.doesNotMatch(
    source,
    /Math\.max\(document\.documentElement\.scrollHeight/,
  );
});

test("iframe bridge observes layout and tab-content changes with coalescing", () => {
  const source = bridgeSource();

  assert.match(source, /new ResizeObserver\(scheduleHeightReport\)/);
  assert.match(source, /new MutationObserver\(scheduleHeightReport\)/);
  assert.match(source, /characterData: true/);
  assert.match(source, /childList: true/);
  assert.match(source, /subtree: true/);
  assert.match(source, /requestAnimationFrame\(run\)/);
});

function katexInitSource(html: string): string {
  const match = injectKaTeX(html).match(
    /<script data-katex-init>([\s\S]*?)<\/script>/,
  );
  assert.ok(match, "injected HTML should contain the KaTeX init script");
  return match[1];
}

test("KaTeX init keeps the $$ display delimiter in every document shape", () => {
  for (const html of [
    "<html><head><title>t</title></head><body>$$x$$</body></html>",
    '<html><head lang="en"><body>$$x$$</body></html>',
    "<html><body>$$x$$</body></html>",
    "<div>$$x$$</div>",
  ]) {
    const source = katexInitSource(html);
    assert.match(source, /left:\s*"\$\$",\s*right:\s*"\$\$",\s*display:\s*true/);
    assert.match(source, /left:\s*"\$",\s*right:\s*"\$",\s*display:\s*false/);
  }
});

test("KaTeX injection keeps the html tag's attributes", () => {
  assert.match(
    injectKaTeX('<html lang="it"><body></body></html>'),
    /^<html lang="it">\n<head>/,
  );
});

test("KaTeX init renders math a widget writes after load", () => {
  const source = katexInitSource("<div></div>");

  assert.match(source, /new MutationObserver\(/);
  assert.match(source, /ignoredClasses: \["katex"\]/);
  assert.match(source, /observer\.disconnect\(\)/);
});

test("prepared html declares the requested color-scheme", () => {
  const dark = prepareIframeHtml("<p>hello figure</p>", "dark");
  assert.match(dark, /<meta name="color-scheme" content="dark">/);
  assert.match(dark, /data-dt-bridge/, "bridge still injected");

  const light = prepareIframeHtml("<p>hello figure</p>", "light");
  assert.match(light, /<meta name="color-scheme" content="light">/);
});

test("system declares both schemes so the browser follows prefers-color-scheme", () => {
  const prepared = prepareIframeHtml("<p>hello figure</p>", "system");
  assert.match(prepared, /<meta name="color-scheme" content="dark light">/);
});

test("a widget that declares its own color-scheme is left alone", () => {
  const declared =
    '<!doctype html><html><head><meta name="color-scheme" content="light"></head><body><p>x</p></body></html>';
  const prepared = prepareIframeHtml(declared, "dark");
  assert.equal(
    prepared.match(/name="color-scheme"/g)!.length,
    1,
    "host must not add a second declaration",
  );
  assert.match(prepared, /content="light"/);

  const cssDeclared =
    "<!doctype html><html><head><style>:root { color-scheme: dark; }</style></head><body><p>x</p></body></html>";
  assert.equal(
    prepareIframeHtml(cssDeclared, "light").match(/meta name="color-scheme"/g),
    null,
  );
});

test("omitting the color scheme keeps the prepared html untouched", () => {
  const prepared = prepareIframeHtml("<p>hello figure</p>");
  assert.doesNotMatch(prepared, /color-scheme/);
});

test("injectColorScheme covers headless and head-less-markup fragments", () => {
  // no head at all: the meta goes into a synthesized document head
  const synthesized = injectColorScheme("<p>x</p>", "dark");
  assert.match(synthesized, /<head>[\s\S]*content="dark"/);

  // <html> without <head>: a head is created for the declaration
  const htmlOnly = injectColorScheme(
    "<html><body><p>x</p></body></html>",
    "light",
  );
  assert.match(
    htmlOnly,
    /<head>\s*<meta name="color-scheme" content="light">/,
  );
});
