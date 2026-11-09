import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { contentLang } from "../lib/content-lang";

const read = (...parts: string[]) =>
  fs.readFileSync(path.join(process.cwd(), ...parts), "utf8");

test("contentLang maps CJK reply languages onto HTML lang tags", () => {
  assert.equal(contentLang(undefined), undefined);
  assert.equal(contentLang(""), undefined);
  assert.equal(contentLang("  "), undefined);

  assert.equal(contentLang("ja"), "ja");
  assert.equal(contentLang("JA"), "ja");
  assert.equal(contentLang("jp"), "ja");
  assert.equal(contentLang("ja-JP"), "ja");

  assert.equal(contentLang("ko"), "ko");
  assert.equal(contentLang("ko_KR"), "ko");
  assert.equal(contentLang("kr"), "ko");

  assert.equal(contentLang("zh-tw"), "zh-Hant");
  assert.equal(contentLang("zh_TW"), "zh-Hant");
  assert.equal(contentLang("zh-Hant"), "zh-Hant");
  assert.equal(contentLang("zh-hk"), "zh-Hant");

  assert.equal(contentLang("zh"), "zh-Hans");
  assert.equal(contentLang("zh-cn"), "zh-Hans");
  assert.equal(contentLang("zh-Hans"), "zh-Hans");

  assert.equal(contentLang("en"), undefined);
  assert.equal(contentLang("fr"), undefined);
  assert.equal(contentLang("pt"), undefined);
});

function stackOrder(css: string, selectorBlock: string, earlier: string, later: string) {
  const idx = css.indexOf(selectorBlock);
  assert.ok(idx >= 0, `missing selector block ${selectorBlock}`);
  const bodyStart = css.indexOf("{", idx);
  const bodyEnd = css.indexOf("}", bodyStart);
  const body = css.slice(bodyStart, bodyEnd);
  const a = body.indexOf(earlier);
  const b = body.indexOf(later);
  assert.ok(a >= 0, `${earlier} missing in ${selectorBlock}`);
  assert.ok(b >= 0, `${later} missing in ${selectorBlock}`);
  assert.ok(a < b, `${earlier} must precede ${later} in ${selectorBlock}`);
}

test("globals.css :lang CJK stacks put regional faces before SimSun/Songti SC", () => {
  const css = read("app/globals.css");

  stackOrder(css, ".prose:lang(ja)", "Yu Mincho", "SimSun");
  stackOrder(css, ".prose:lang(ja)", "Noto Serif JP", "SimSun");
  stackOrder(css, ".prose:lang(ja)", "Hiragino Mincho ProN", "Songti SC");

  stackOrder(css, ".prose:lang(ko)", "Noto Serif KR", "SimSun");
  stackOrder(css, ".prose:lang(ko)", "Batang", "Songti SC");

  stackOrder(css, ".prose:lang(zh-Hant)", "Songti TC", "SimSun");
  stackOrder(css, ".prose:lang(zh-Hant)", "Noto Serif TC", "Songti SC");

  const tw = read("tailwind.config.js");
  const serifIdx = tw.indexOf("serif:");
  const serifSlice = tw.slice(serifIdx, serifIdx + 400);
  assert.ok(serifSlice.includes("Songti SC"));
  assert.ok(!serifSlice.includes("Yu Mincho"));
  assert.ok(!serifSlice.includes("Noto Serif JP"));
});

test("AssistantResponse sets lang from contentLang(language)", () => {
  const src = read("components/common/AssistantResponse.tsx");
  assert.match(src, /import \{ contentLang \} from "@\/lib\/content-lang"/);
  assert.match(src, /lang=\{contentLang\(language\)\}/);
});
