import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

// The /whisper surface shipped with 23 hardcoded strings — mostly English plus
// one stray Chinese button — so it rendered the same copy whatever language the
// user had picked. Now that every one goes through `t()`, pin the other half of
// that contract: each key must exist in both locales, and the Chinese side must
// actually be translated rather than echoing the English back.

function findWebRoot(): string {
  let dir = __dirname;
  for (let i = 0; i < 8; i++) {
    if (fs.existsSync(path.join(dir, "locales", "en", "app.json"))) return dir;
    dir = path.dirname(dir);
  }
  throw new Error("could not locate the web root from " + __dirname);
}

const WEB = findWebRoot();

const SOURCES = [
  "app/(workspace)/whisper/page.tsx",
  "components/whisper/WhisperComposer.tsx",
  "components/whisper/WhisperMessageList.tsx",
  "components/whisper/WhisperRoomChip.tsx",
];

// `t("…")` but not `setDraft("")` — the negative lookbehind keeps identifiers
// that merely end in `t` from matching.
const T_CALL = /(?<![\w$])t\(\s*"((?:[^"\\]|\\.)+)"/g;

function keysUsed(): string[] {
  const keys = new Set<string>();
  for (const rel of SOURCES) {
    const src = fs.readFileSync(path.join(WEB, rel), "utf8");
    for (const m of src.matchAll(T_CALL)) keys.add(m[1]);
  }
  return [...keys].sort();
}

function locale(name: string): Record<string, string> {
  return JSON.parse(
    fs.readFileSync(path.join(WEB, "locales", name, "app.json"), "utf8"),
  ) as Record<string, string>;
}

test("the whisper surface actually calls t() for its copy", () => {
  // Guards the regex itself: if these files stop using t(), the assertions
  // below would pass vacuously.
  assert.ok(
    keysUsed().length >= 25,
    `expected the whisper files to translate their copy, found ${keysUsed().length} keys`,
  );
});

test("every whisper translation key exists in both locales", () => {
  const en = locale("en");
  const zh = locale("zh");
  const missing = keysUsed().filter((k) => !(k in en) || !(k in zh));
  assert.deepEqual(
    missing,
    [],
    `keys missing from a locale (they would render as raw English): ${missing.join(", ")}`,
  );
});

test("whisper copy is really translated into Chinese", () => {
  const zh = locale("zh");
  // Interpolated placeholders and bare ids are legitimately identical across
  // locales; prose is not.
  const echoed = keysUsed().filter(
    (k) => k.length > 3 && !k.includes("{{") && zh[k] === k,
  );
  assert.deepEqual(
    echoed,
    [],
    `zh still echoes the English copy for: ${echoed.join(", ")}`,
  );
});

test("no hardcoded Chinese copy is left in the whisper components", () => {
  // The End-session button used to be a literal 结束 in the JSX, which showed
  // Chinese to English users. Copy belongs in the locale files.
  //
  // Only the components are checked. page.tsx legitimately holds Chinese
  // *protocol* strings — it sends `结束` as psych-academy's is_end_command and
  // matches the room-ended text the capability streams back. Those are wire
  // values, not copy, and translating them would break the exchange.
  const offenders: string[] = [];
  for (const rel of SOURCES.filter((f) => f.startsWith("components/"))) {
    const src = fs.readFileSync(path.join(WEB, rel), "utf8");
    if (/[一-鿿]/.test(src)) offenders.push(rel);
  }
  assert.deepEqual(
    offenders,
    [],
    `CJK copy left in source: ${offenders.join(", ")}`,
  );
});
