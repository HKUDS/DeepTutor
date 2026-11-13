import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

function findLocalesRoot(): string {
  let dir = __dirname
  for (let i = 0; i < 8; i++) {
    const candidate = path.join(dir, 'locales', 'tr', 'app.json')
    if (fs.existsSync(candidate)) return path.join(dir, 'locales')
    dir = path.dirname(dir)
  }
  throw new Error('could not locate locales/tr/app.json')
}

const localesRoot = findLocalesRoot()
const readCatalog = (locale: string) =>
  JSON.parse(fs.readFileSync(path.join(localesRoot, locale, 'app.json'), 'utf8')) as Record<
    string,
    string
  >
const catalog = readCatalog('tr')
// The `i` flag does not fold İ to i, so matching runs on Turkish-lowercased text.
const lowered = Object.values(catalog).join('\n').toLocaleLowerCase('tr')

// \b only knows ASCII word characters and would split words at ç, ğ, ı, ö, ş, ü.
function containsWord(text: string, word: string): boolean {
  const escaped = word.toLocaleLowerCase('tr').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(?<![\\p{L}\\p{M}\\p{N}_])${escaped}(?![\\p{L}\\p{M}\\p{N}_])`, 'u').test(text)
}

// Turkish attaches case and possessive suffixes, so a rejected stem must match inflected forms too.
function containsStem(text: string, stem: string): boolean {
  const escaped = stem.toLocaleLowerCase('tr').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(?<![\\p{L}\\p{M}\\p{N}_])${escaped}`, 'u').test(text)
}

test('Turkish activity labels describe actions in progress', () => {
  assert.equal(catalog['Reading skill'], 'Skill okunuyor')
  assert.equal(catalog['Reading source'], 'Kaynak okunuyor')
  assert.equal(catalog['Writing file'], 'Dosya yazılıyor')
  assert.equal(catalog['Listing files'], 'Dosyalar listeleniyor')
  assert.equal(catalog['Writing note'], 'Not yazılıyor')
  assert.equal(catalog['Saving memory'], 'Bellek kaydediliyor')
  assert.equal(catalog['Brainstorming'], 'Fikirler toplanıyor')
})

test('Turkish UI keeps the product glossary', () => {
  assert.equal(catalog['Knowledge Base'], 'Bilgi Bankası')
  assert.equal(catalog['Mastery Path'], 'Ustalık Yolu')
  assert.equal(catalog['Guided Learning'], 'Rehberli Öğrenme')
  assert.equal(catalog['Question Bank'], 'Soru Bankası')
  assert.equal(catalog['Learning Space'], 'Öğrenme Alanı')
  assert.equal(catalog['New chat'], 'Yeni sohbet')
  assert.equal(catalog['Sign in'], 'Oturum aç')
  assert.equal(catalog['Save'], 'Kaydet')
  assert.equal(catalog['Cancel'], 'İptal')
  assert.equal(catalog['Retry'], 'Yeniden dene')
})

test('Turkish UI keeps one term per concept', () => {
  // Variants that appeared while the catalog was translated in parallel passes.
  const offGlossary = [
    'Bilgi Tabanı',
    'Bilgi Deposu',
    'Uzmanlık Yolu',
    'Hafıza',
    'Doküman',
    'Seans',
    'Temsilci',
    'Tedarikçi',
    'Kabiliyet',
    'Senkronize',
    'Giriş yap',
    'Çıkış yap',
    'Flaş kart',
    'İndeks',
    'Yapay zeka',
    'Öğrenme Space',
  ]
  for (const term of offGlossary) {
    assert.equal(containsStem(lowered, term), false, `Found off-glossary term: ${term}`)
  }
})

test('Turkish UI addresses the reader consistently with siz', () => {
  for (const polite of [
    'seçiniz',
    'giriniz',
    'deneyiniz',
    'bekleyiniz',
    'yapınız',
    'tıklayınız',
    'ediniz',
  ]) {
    assert.equal(containsWord(lowered, polite), false, `Found over-polite imperative: ${polite}`)
  }
  for (const informal of ['senin', 'sana', 'seni']) {
    assert.equal(containsWord(lowered, informal), false, `Found informal address: ${informal}`)
  }
})

test('Turkish UI avoids the em and en dash', () => {
  const text = Object.entries(catalog)
    .filter(([key]) => !key.includes('Missing measurements appear as —'))
    .map(([, value]) => value)
    .join('\n')
  assert.equal(/[—–]/.test(text), false, 'Found em or en dash in Turkish catalog')
})

test('every catalog names Turkish by its endonym', () => {
  for (const locale of fs.readdirSync(localesRoot).filter(name =>
    fs.existsSync(path.join(localesRoot, name, 'app.json'))
  )) {
    assert.equal(readCatalog(locale)['language.turkish'], 'Türkçe', locale)
  }
})
