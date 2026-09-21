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

function reportUntranslatedKeys() {
  const localeDir = path.join(webRoot, "locales");
  if (!fs.existsSync(localeDir)) return;
  const locales = fs
    .readdirSync(localeDir, { withFileTypes: true })
    .filter((ent) => ent.isDirectory())
    .map((ent) => ent.name);
  if (!locales.length) return;

  const known = new Map();
  for (const locale of locales) {
    const file = path.join(localeDir, locale, "app.json");
    if (!fs.existsSync(file)) continue;
    known.set(locale, new Set(Object.keys(JSON.parse(fs.readFileSync(file, "utf8")))));
  }

  const missing = new Map();
  const roots = ["app", "components", "features", "hooks", "lib", "shared"]
    .map((dir) => path.join(webRoot, dir))
    .filter((dir) => fs.existsSync(dir));
  for (const dir of roots) {
    for (const file of listCodeFiles(dir)) {
      const content = fs.readFileSync(file, "utf8");
      for (const key of translationKeys(file, content)) {
        if (!key) continue;
        for (const [locale, keys] of known) {
          const pluralForms = new Intl.PluralRules(locale).resolvedOptions().pluralCategories;
          if (keys.has(key) || pluralForms.every((form) => keys.has(`${key}_${form}`))) continue;
          if (!missing.has(locale)) missing.set(locale, new Set());
          missing.get(locale).add(key);
        }
      }
    }
  }

  const summary = [...missing.entries()]
    .filter(([, keys]) => keys.size)
    .map(([locale, keys]) => `${locale}: ${keys.size}`);
  if (!summary.length) {
    console.log("[i18n:audit] every t() literal has an entry in each locale");
    return;
  }
  process.exitCode = 1;
  console.log(
    `[i18n:audit] t() literals with no locale entry — ${summary.join(", ")} ` +
      `(they render as their English key). Run with --show-missing to list them.`,
  );
  if (!process.argv.includes("--show-missing")) return;
  for (const [locale, keys] of missing) {
    if (!keys.size) continue;
    console.log(`\n- ${locale}`);
    for (const key of [...keys].sort()) console.log(`  - ${JSON.stringify(key)}`);
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
