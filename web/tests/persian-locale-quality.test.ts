import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

function findLocalesRoot(): string {
  let dir = __dirname
  for (let i = 0; i < 8; i++) {
    const candidate = path.join(dir, 'locales', 'fa', 'app.json')
    if (fs.existsSync(candidate)) return path.join(dir, 'locales')
    dir = path.dirname(dir)
  }
  throw new Error('could not locate locales/fa/app.json')
}

const localesRoot = findLocalesRoot()
const readCatalog = (locale: string) =>
  JSON.parse(fs.readFileSync(path.join(localesRoot, locale, 'app.json'), 'utf8')) as Record<
    string,
    string
  >
const catalog = readCatalog('fa')
const text = Object.values(catalog).join('\n')

// Persian has no letter casing; word boundaries are spaces and ZWNJ (U+200C,
// a format character, so the \\p{L} lookarounds treat it as a boundary).
function containsWord(text: string, word: string): boolean {
  const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(?<![\\p{L}\\p{M}\\p{N}_])${escaped}(?![\\p{L}\\p{M}\\p{N}_])`, 'u').test(text)
}

function containsStem(text: string, stem: string): boolean {
  const escaped = stem.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(?<![\\p{L}\\p{M}\\p{N}_])${escaped}`, 'u').test(text)
}

test('Persian activity labels describe actions in progress', () => {
  assert.equal(catalog['Reading skill'], 'در حال خواندن مهارت')
  assert.equal(catalog['Reading source'], 'در حال خواندن منبع')
  assert.equal(catalog['Writing file'], 'در حال نوشتن فایل')
  assert.equal(catalog['Listing files'], 'در حال فهرست فایل‌ها')
  assert.equal(catalog['Writing note'], 'در حال نوشتن یادداشت')
  assert.equal(catalog['Saving memory'], 'در حال ذخیره حافظه')
  assert.equal(catalog['Brainstorming'], 'طوفان فکری')
})

test('Persian UI keeps the product glossary', () => {
  assert.equal(catalog['Knowledge Base'], 'پایگاه دانش')
  assert.equal(catalog['Mastery Path'], 'مسیر تسلط')
  assert.equal(catalog['Guided Learning'], 'یادگیری هدایت‌شده')
  assert.equal(catalog['Question Bank'], 'بانک پرسش')
  assert.equal(catalog['Learning Space'], 'فضای یادگیری')
  assert.equal(catalog['New chat'], 'چت جدید')
  assert.equal(catalog['Sign in'], 'ورود')
  assert.equal(catalog['Save'], 'ذخیره')
  assert.equal(catalog['Cancel'], 'لغو')
  assert.equal(catalog['Retry'], 'تلاش مجدد')
})

test('Persian orthography joins with ZWNJ, not spaces', () => {
  // می‌ prefixes and compound words must use U+200C, not a plain space.
  assert.equal(catalog['Flash Cards'], 'فلش\u200cکارت\u200cها')
  assert.equal(catalog['Export flashcards (Anki)'], 'برون\u200cبری فلش\u200cکارت\u200cها (Anki)')
  assert.match(catalog['Saving memory'], /ذخیره حافظه$/)
})

test('Persian UI keeps one term per concept', () => {
  // Variants that appeared while the catalog was translated in parallel passes.
  const offGlossary = [
    'مسیر استادی',
    'یادگیری راهنمایی‌شده',
    'بانک سؤال',
    'فضای آموزش',
    'ورود به سیستم',
    'خروج از حساب',
    'کارت حافظه',
    'پایگاه داده',
  ]
  for (const term of offGlossary) {
    assert.equal(containsStem(text, term), false, `Found off-glossary term: ${term}`)
  }
})

test('Persian UI addresses the reader informally', () => {
  // The catalog speaks with «تو»; these are formal-register leftovers.
  for (const formal of [
    'نمایید',
    'بفرمایید',
    'خواهید',
    'می‌توانید',
    'داشته باشید',
    'بدهید',
    'بروید',
    'بخوانید',
    'انتخاب کنید',
    'کلیک کنید',
    'تلاش کنید',
  ]) {
    assert.equal(text.includes(formal), false, `Found formal register: ${formal}`)
  }
})

test('every catalog names Persian by its endonym', () => {
  for (const locale of fs.readdirSync(localesRoot).filter(name =>
    fs.existsSync(path.join(localesRoot, name, 'app.json'))
  )) {
    assert.equal(readCatalog(locale)['language.persian'], 'فارسی', locale)
  }
})
