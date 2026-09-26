import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

function listCodeFiles(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "node_modules" || ent.name === ".next") continue;
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...listCodeFiles(full));
    else if (ent.isFile() && /\.tsx?$/.test(ent.name)) out.push(full);
  }
  return out;
}

function toRel(p, root) {
  return path.relative(root, p).replaceAll("\\", "/");
}

function hasUiText(s) {
  // Very rough heuristic: letters / CJK / common punctuation sequences
  return /[A-Za-z\u4e00-\u9fff]/.test(s);
}

function auditFile(content, file) {
  const findings = [];
  const source = ts.createSourceFile(file, content, ts.ScriptTarget.Latest, true);
  const attrs = new Set(["title", "placeholder", "alt", "aria-label"]);
  function add(kind, raw) {
    const text = raw.replace(/\s+/g, " ").trim();
    if (text.length > 1 && hasUiText(text) && text !== "DeepTutor") {
      findings.push({ kind, text });
    }
  }
  function visit(node) {
    if (ts.isJsxText(node)) add("jsxText", node.text);
    if (ts.isJsxAttribute(node) && attrs.has(node.name.getText(source))) {
      if (node.initializer && ts.isStringLiteral(node.initializer)) {
        add(`attr:${node.name.getText(source)}`, node.initializer.text);
      }
    }
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) &&
        ["alert", "confirm"].includes(node.expression.text)) {
      for (const text of literalKeys(node.arguments[0])) add(`${node.expression.text}()`, text);
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  return findings;
}

const webRoot = path.resolve(process.cwd());
const targets = ["app", "components", "features", "hooks", "lib", "shared"]
  .map((dir) => path.join(webRoot, dir))
  .filter((dir) => fs.existsSync(dir));

const strict = process.argv.includes("--strict");
const fileFilterIdx = process.argv.indexOf("--file");
const fileFilter =
  fileFilterIdx >= 0 ? String(process.argv[fileFilterIdx + 1] || "").trim() : "";
const showAll = process.argv.includes("--show-all");

/** Parse literal keys without mistaking comments, escapes or plural keys for gaps. */
function literalKeys(expression) {
  if (!expression) return [];
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
    return [expression.text];
  }
  if (ts.isConditionalExpression(expression)) {
    return [...literalKeys(expression.whenTrue), ...literalKeys(expression.whenFalse)];
  }
  return [];
}

function translationKeys(file, content) {
  const source = ts.createSourceFile(file, content, ts.ScriptTarget.Latest, true);
  const keys = new Set();
  function visit(node) {
    if (ts.isCallExpression(node)) {
      const callee = node.expression;
      const isTranslation =
        (ts.isIdentifier(callee) && callee.text === "t") ||
        (ts.isPropertyAccessExpression(callee) && callee.name.text === "t");
      if (isTranslation) {
        for (const key of literalKeys(node.arguments[0])) keys.add(key);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  return keys;
}

const REQUIRED_LOCALES = ["en", "zh", "fr", "de", "uk"];
// French and Ukrainian are deliberately partial. i18next falls back to the
// English resource per key; these floors make a coverage regression visible.
const MIN_USED_COVERAGE = new Map([
  ["fr", 0.65],
  ["uk", 0.75],
]);

function hasTranslation(entries, pluralForms, key) {
  if (Object.hasOwn(entries, key)) return true;
  return pluralForms.every((form) => Object.hasOwn(entries, `${key}_${form}`));
}

function placeholders(value) {
  if (typeof value !== "string") return new Set();
  return new Set([...value.matchAll(/\{\{\s*([^{}]+?)\s*\}\}/g)].map((match) => match[1].trim()));
}

function placeholderMismatches(english, localized) {
  const mismatches = [];
  for (const [key, translation] of Object.entries(localized)) {
    if (!Object.hasOwn(english, key)) continue;
    const expected = placeholders(english[key]);
    const actual = placeholders(translation);
    const missing = [...expected].filter((name) => !actual.has(name));
    const extra = [...actual].filter(
      (name) => !expected.has(name) && !(name === "count" && /_(zero|one|two|few|many|other)$/.test(key)),
    );
    if (missing.length || extra.length) mismatches.push({ key, missing, extra });
  }
  return mismatches;
}

function reportUntranslatedKeys() {
  const localeDir = path.join(webRoot, "locales");
  if (!fs.existsSync(localeDir)) {
    console.error("[i18n:audit] Missing locales directory");
    process.exitCode = 1;
    return;
  }
  const locales = new Set(REQUIRED_LOCALES);
  for (const ent of fs.readdirSync(localeDir, { withFileTypes: true })) {
    if (ent.isDirectory()) locales.add(ent.name);
  }

  const known = new Map();
  for (const locale of locales) {
    const file = path.join(localeDir, locale, "app.json");
    if (!fs.existsSync(file)) {
      console.error(`[i18n:audit] Missing ${locale}/app.json`);
      process.exitCode = 1;
      continue;
    }
    known.set(locale, JSON.parse(fs.readFileSync(file, "utf8")));
  }
  const english = known.get("en");
  if (!english) return;

  const usedKeys = new Set();
  const roots = ["app", "components", "features", "hooks", "lib", "shared"]
    .map((dir) => path.join(webRoot, dir))
    .filter((dir) => fs.existsSync(dir));
  for (const dir of roots) {
    for (const file of listCodeFiles(dir)) {
      const content = fs.readFileSync(file, "utf8");
      for (const key of translationKeys(file, content)) {
        if (key) usedKeys.add(key);
      }
    }
  }

  const englishKeys = new Set(Object.keys(english));
  for (const [locale, entries] of known) {
    const pluralForms = new Intl.PluralRules(locale).resolvedOptions().pluralCategories;
    const missing = [...usedKeys].filter((key) => !hasTranslation(entries, pluralForms, key));
    const translated = usedKeys.size - missing.length;
    const usedCoverage = usedKeys.size ? translated / usedKeys.size : 1;
    const catalogTranslated = [...englishKeys].filter((key) => Object.hasOwn(entries, key)).length;
    const catalogCoverage =
      englishKeys.size
        ? catalogTranslated / englishKeys.size
        : 1;
    const formatPercent = (ratio) => `${(ratio * 100).toFixed(1)}%`;
    const floor = MIN_USED_COVERAGE.get(locale);

    if (floor === undefined) {
      console.log(`[i18n:audit] ${locale}: ${translated}/${usedKeys.size} used keys (${formatPercent(usedCoverage)}), strict`);
      if (missing.length) {
        console.error(`[i18n:audit] ${locale}: ${missing.length} t() literals lack a locale entry`);
        process.exitCode = 1;
      }
    } else {
      console.log(
        `[i18n:audit] ${locale}: ${translated}/${usedKeys.size} used keys (${formatPercent(usedCoverage)}); ` +
          `${catalogTranslated}/${englishKeys.size} English catalog keys (${formatPercent(catalogCoverage)}); ` +
          `${missing.length} used keys fall back to English ` +
          `(minimum ${formatPercent(floor)} used coverage)`,
      );
      if (usedCoverage < floor) {
        console.error(`[i18n:audit] ${locale}: used-key coverage below ${formatPercent(floor)}`);
        process.exitCode = 1;
      }
    }

    if (process.argv.includes("--show-missing") && missing.length) {
      console.log(`\n- ${locale} missing used keys`);
      for (const key of missing.sort()) console.log(`  - ${JSON.stringify(key)}`);
    }
    if (locale === "en") continue;
    const mismatches = placeholderMismatches(english, entries);
    if (mismatches.length) {
      process.exitCode = 1;
      console.error(`[i18n:audit] ${locale}: ${mismatches.length} interpolation placeholder mismatches`);
      for (const { key, missing: lost, extra } of mismatches.slice(0, 20)) {
        console.error(`  ${JSON.stringify(key)}: missing [${lost.join(", ")}], extra [${extra.join(", ")}]`);
      }
    }
  }
}

reportUntranslatedKeys();

const allFindings = [];
for (const dir of targets) {
  const files = listCodeFiles(dir);
  for (const f of files) {
    if (fileFilter && !toRel(f, webRoot).includes(fileFilter)) continue;
    const content = fs.readFileSync(f, "utf8");
    const findings = auditFile(content, f);
    if (findings.length) {
      allFindings.push({
        file: toRel(f, webRoot),
        findings,
      });
    }
  }
}

if (!allFindings.length) {
  console.log("[i18n:audit] OK (no obvious UI literals found)");
  process.exit(process.exitCode || 0);
}

console.log(`[i18n:audit] Found ${allFindings.length} files with potential UI literals`);
const fileLimit = showAll ? allFindings.length : 80;
for (const item of allFindings.slice(0, fileLimit)) {
  console.log(`\n- ${item.file}`);
  const perFileLimit = showAll ? item.findings.length : 10;
  for (const f of item.findings.slice(0, perFileLimit)) {
    console.log(`  - ${f.kind}: ${JSON.stringify(f.text)}`);
  }
  if (!showAll && item.findings.length > 10)
    console.log(`  - ... +${item.findings.length - 10} more`);
}
if (!showAll && allFindings.length > 80)
  console.log(`\n... and ${allFindings.length - 80} more files`);

if (strict) process.exit(1);
process.exit(process.exitCode || 0);
