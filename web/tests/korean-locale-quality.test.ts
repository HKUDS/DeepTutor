import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

function findLocalesRoot(): string {
  let dir = __dirname
  for (let i = 0; i < 8; i++) {
    const candidate = path.join(dir, 'locales')
    if (fs.existsSync(path.join(candidate, 'ko', 'common.json'))) return candidate
    dir = path.dirname(dir)
  }
  throw new Error('could not locate locales/ko/app.json')
}

const localesRoot = findLocalesRoot()
const readCatalog = (locale: string, file = 'app.json') =>
  JSON.parse(fs.readFileSync(path.join(localesRoot, locale, file), 'utf8')) as Record<
    string,
    string
  >

// Match entire placeholder tokens, including brace count and formatting.
const placeholders = (value: string) =>
  [...value.matchAll(/\{\{[^{}]+\}\}|(?<!\{)\{[^{}]+\}(?!\})/g)].map(match => match[0]).sort()

test('Korean catalogs preserve source keys and all placeholder tokens', () => {
  for (const file of ['app.json', 'common.json']) {
    const source = readCatalog('en', file)
    for (const [key, value] of Object.entries(readCatalog('ko', file))) {
      assert.ok(Object.hasOwn(source, key), `Unknown key: ${key}`)
      assert.ok(value.trim(), `Empty translation: ${key}`)
      assert.deepEqual(placeholders(value), placeholders(source[key]), key)
    }
  }
})

test('Korean common catalog is complete and agrees with the app catalog', () => {
  const common = readCatalog('ko', 'common.json')
  const app = readCatalog('ko')
  assert.deepEqual(Object.keys(common).sort(), Object.keys(readCatalog('en', 'common.json')).sort())
  for (const [key, value] of Object.entries(common)) assert.equal(value, app[key], key)
})

test('every locale offers Korean by its endonym', () => {
  for (const locale of fs.readdirSync(localesRoot)) {
    if (!fs.existsSync(path.join(localesRoot, locale, 'app.json'))) continue
    assert.equal(readCatalog(locale)['language.korean'], '한국어 (일부 번역)', locale)
  }
})
