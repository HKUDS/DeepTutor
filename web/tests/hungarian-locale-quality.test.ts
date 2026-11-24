import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

function findLocalesRoot(): string {
  let dir = __dirname
  for (let i = 0; i < 8; i++) {
    const candidate = path.join(dir, 'locales', 'hu', 'app.json')
    if (fs.existsSync(candidate)) return path.join(dir, 'locales')
    dir = path.dirname(dir)
  }
  throw new Error('could not locate locales/hu/app.json')
}

const localesRoot = findLocalesRoot()
const readCatalog = (locale: string) =>
  JSON.parse(fs.readFileSync(path.join(localesRoot, locale, 'app.json'), 'utf8')) as Record<
    string,
    string
  >
const catalog = readCatalog('hu')
// \b only knows ASCII word characters and would split Hungarian words at á, é, ő, ű.
function containsWord(text: string, word: string): boolean {
  const escaped = word.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(?<![\\p{L}\\p{M}\\p{N}_])${escaped}(?![\\p{L}\\p{M}\\p{N}_])`, 'u').test(text)
}
const values = Object.values(catalog).join('\n')

test('Hungarian UI keeps the product glossary', () => {
  assert.equal(catalog['Knowledge Base'], 'Tudásbázis')
  assert.equal(catalog['Mastery Path'], 'Elsajátítási útvonal')
  assert.equal(catalog['Guided Learning'], 'Irányított tanulás')
  assert.equal(catalog['Question Bank'], 'Kérdésbank')
  assert.equal(catalog['Learning Space'], 'Tanulótér')
  assert.equal(catalog['New chat'], 'Új csevegés')
  assert.equal(catalog['Sign in'], 'Bejelentkezés')
  assert.equal(catalog['Save'], 'Mentés')
  assert.equal(catalog['Cancel'], 'Mégsem')
  assert.equal(catalog['Retry'], 'Újrapróbálkozás')
})

test('Hungarian UI addresses the reader formally', () => {
  // The catalog speaks to the reader as Ön; the informal imperative would read
  // like a chat with a friend and clash with the rest of the interface.
  const informal = [
    'kattints',
    'válaszd',
    'nyisd',
    'írd',
    'töltsd',
    'másold',
    'használd',
    'próbáld',
    'nézd',
    'kérdezz',
    'neked',
    'téged',
  ]
  for (const word of informal) {
    assert.equal(containsWord(values, word), false, `Found informal address: ${word}`)
  }
})

test('Hungarian UI uses the en dash, never the em dash', () => {
  // Hungarian separates an apposition with a spaced en dash (–); the em dash is
  // an English convention and reading it as one has no Hungarian precedent.
  const offenders = Object.entries(catalog)
    .filter(([, value]) => value.includes('\u2014'))
    .map(([key]) => key)
  assert.deepEqual(offenders, [])
})

test('every catalog names Hungarian by its endonym', () => {
  for (const locale of fs
    .readdirSync(localesRoot)
    .filter(name => fs.existsSync(path.join(localesRoot, name, 'app.json')))) {
    assert.equal(readCatalog(locale)['language.hungarian'], 'Magyar', locale)
  }
})
