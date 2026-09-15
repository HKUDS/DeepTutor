import fs from 'node:fs'
import path from 'node:path'

function listJsonFiles(dir) {
  const out = []
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name)
    if (ent.isDirectory()) out.push(...listJsonFiles(full))
    else if (ent.isFile() && ent.name.endsWith('.json')) out.push(full)
  }
  return out
}

function loadJson(p) {
  return JSON.parse(fs.readFileSync(p, 'utf8'))
}

function flattenValues(obj, prefix = '', out = new Map()) {
  if (!obj || typeof obj !== 'object') return out
  for (const [key, value] of Object.entries(obj)) {
    const next = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      flattenValues(value, next, out)
    } else {
      out.set(next, value)
    }
  }
  return out
}

function interpolationFields(value) {
  if (typeof value !== 'string') return []
  return [...value.matchAll(/{{\s*([^{}]+?)\s*}}/g)].map(match => match[1].trim()).sort()
}

function toRel(p, root) {
  return path.relative(root, p).replaceAll('\\', '/')
}

const webRoot = path.resolve(process.cwd())
const localesRoot = path.join(webRoot, 'locales')
const enRoot = path.join(localesRoot, 'en')

if (!fs.existsSync(enRoot)) {
  console.error(`[i18n:parity] Missing source locale root: ${enRoot}`)
  process.exit(2)
}

const enFiles = listJsonFiles(enRoot)
  .map(p => toRel(p, enRoot))
  .sort()
let ok = true
const localeNames = fs
  .readdirSync(localesRoot, { withFileTypes: true })
  .filter(entry => entry.isDirectory() && entry.name !== 'en')
  .map(entry => entry.name)
  .sort()

for (const locale of localeNames) {
  const localeRoot = path.join(localesRoot, locale)
  const localeFiles = listJsonFiles(localeRoot)
    .map(p => toRel(p, localeRoot))
    .sort()
  const missingFiles = enFiles.filter(file => !localeFiles.includes(file))
  const extraFiles = localeFiles.filter(file => !enFiles.includes(file))

  if (missingFiles.length || extraFiles.length) {
    ok = false
    if (missingFiles.length) {
      console.error(`[i18n:parity] Missing ${locale} files:`)
      for (const file of missingFiles) console.error(`- ${file}`)
    }
    if (extraFiles.length) {
      console.error(`[i18n:parity] Extra ${locale} files:`)
      for (const file of extraFiles) console.error(`- ${file}`)
    }
  }

  for (const rel of enFiles) {
    if (!localeFiles.includes(rel)) continue
    const enValues = flattenValues(loadJson(path.join(enRoot, rel)))
    const localeValues = flattenValues(loadJson(path.join(localeRoot, rel)))
    const enKeys = new Set(enValues.keys())
    const localeKeys = new Set(localeValues.keys())
    const missingKeys = [...enKeys].filter(key => !localeKeys.has(key)).sort()
    const extraKeys = [...localeKeys].filter(key => !enKeys.has(key)).sort()

    if (missingKeys.length || extraKeys.length) {
      ok = false
      console.error(`[i18n:parity] Key mismatch in ${locale}/${rel}`)
      if (missingKeys.length) {
        console.error(`  Missing ${locale} keys:`)
        for (const key of missingKeys) console.error(`  - ${key}`)
      }
      if (extraKeys.length) {
        console.error(`  Extra ${locale} keys:`)
        for (const key of extraKeys) console.error(`  - ${key}`)
      }
    }

    for (const key of [...enKeys].filter(item => localeKeys.has(item))) {
      const expected = interpolationFields(enValues.get(key))
      const actual = interpolationFields(localeValues.get(key))
      if (JSON.stringify(actual) === JSON.stringify(expected)) continue
      ok = false
      console.error(`[i18n:parity] Placeholder mismatch in ${locale}/${rel}: ${key}`)
      console.error(`  Expected: ${expected.join(', ') || '(none)'}`)
      console.error(`  Actual: ${actual.join(', ') || '(none)'}`)
    }
  }
}

if (!ok) process.exit(1)
console.log('[i18n:parity] OK')
