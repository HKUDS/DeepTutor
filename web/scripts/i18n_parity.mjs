import fs from "node:fs";
import path from "node:path";

function listJsonFiles(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...listJsonFiles(full));
    else if (ent.isFile() && ent.name.endsWith(".json")) out.push(full);
  }
  return out;
}

function loadJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function flattenKeys(obj, prefix = "") {
  const keys = [];
  if (!obj || typeof obj !== "object") return keys;
  for (const [k, v] of Object.entries(obj)) {
    const next = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) keys.push(...flattenKeys(v, next));
    else keys.push(next);
  }
  return keys;
}

function toRel(p, root) {
  return path.relative(root, p).replaceAll("\\", "/");
}

const webRoot = path.resolve(process.cwd());
const localesRoot = path.join(webRoot, "locales");
const enRoot = path.join(localesRoot, "en");

if (!fs.existsSync(enRoot)) {
  console.error(`[i18n:parity] Missing English locale root: ${enRoot}`);
  process.exit(2);
}

const enFiles = listJsonFiles(enRoot).map((p) => toRel(p, enRoot)).sort();
const localeNames = fs
  .readdirSync(localesRoot, { withFileTypes: true })
  .filter((ent) => ent.isDirectory() && ent.name !== "en")
  .map((ent) => ent.name)
  .sort();

if (localeNames.length === 0) {
  console.error(`[i18n:parity] No non-English locale roots found in ${localesRoot}`);
  process.exit(2);
}

let ok = true;

for (const locale of localeNames) {
  const localeRoot = path.join(localesRoot, locale);
  const localeFiles = listJsonFiles(localeRoot)
    .map((p) => toRel(p, localeRoot))
    .sort();

  const missingFiles = enFiles.filter((f) => !localeFiles.includes(f));
  const extraFiles = localeFiles.filter((f) => !enFiles.includes(f));

  if (missingFiles.length) {
    ok = false;
    console.error(`[i18n:parity] Missing ${locale} files:`);
    for (const f of missingFiles) console.error(`- ${f}`);
  }
  if (extraFiles.length) {
    ok = false;
    console.error(`[i18n:parity] Extra ${locale} files:`);
    for (const f of extraFiles) console.error(`- ${f}`);
  }

  for (const rel of enFiles) {
    if (!localeFiles.includes(rel)) continue;
    const enPath = path.join(enRoot, rel);
    const localePath = path.join(localeRoot, rel);
    const enJson = loadJson(enPath);
    const localeJson = loadJson(localePath);
    const enKeys = new Set(flattenKeys(enJson));
    const localeKeys = new Set(flattenKeys(localeJson));

    const missingKeys = [...enKeys].filter((k) => !localeKeys.has(k)).sort();
    const extraKeys = [...localeKeys].filter((k) => !enKeys.has(k)).sort();

    if (missingKeys.length || extraKeys.length) {
      ok = false;
      console.error(`[i18n:parity] Key mismatch in ${locale}/${rel}`);
      if (missingKeys.length) {
        console.error(`  Missing ${locale} keys:`);
        for (const k of missingKeys) console.error(`  - ${k}`);
      }
      if (extraKeys.length) {
        console.error(`  Extra ${locale} keys:`);
        for (const k of extraKeys) console.error(`  - ${k}`);
      }
    }
  }
}

if (!ok) process.exit(1);
console.log(`[i18n:parity] OK (${localeNames.join(", ")})`);
