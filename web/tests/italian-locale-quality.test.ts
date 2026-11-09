import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

function findLocalesRoot(): string {
  let dir = typeof __dirname !== 'undefined' ? __dirname : path.dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 8; i++) {
    const candidate = path.join(dir, 'locales', 'it', 'app.json')
    if (fs.existsSync(candidate)) return path.join(dir, 'locales')
    dir = path.dirname(dir)
  }
  throw new Error('could not locate locales/it/app.json')
}

const localesRoot = findLocalesRoot()
const readCatalog = (locale: string) =>
  JSON.parse(fs.readFileSync(path.join(localesRoot, locale, 'app.json'), 'utf8')) as Record<
    string,
    string
  >
const catalog = readCatalog('it')

test('Italian activity labels describe actions in progress', () => {
  assert.equal(catalog['Reading skill'], 'Lettura della competenza in corso')
  assert.equal(catalog['Reading source'], 'Lettura della fonte in corso')
  assert.equal(catalog['Writing file'], 'Scrittura del file in corso')
  assert.equal(catalog['Listing files'], 'Elenco dei file in corso')
  assert.equal(catalog['Writing note'], 'Scrittura della nota in corso')
  assert.equal(catalog['Saving memory'], 'Salvataggio della memoria in corso')
  assert.equal(catalog['Brainstorming'], 'Raccolta di idee in corso')
})

test('Italian UI keeps the product glossary', () => {
  assert.equal(catalog['Knowledge Base'], 'Base di conoscenza')
  assert.equal(catalog['Mastery Path'], 'Percorso di padronanza')
  assert.equal(catalog['Guided Learning'], 'Apprendimento guidato')
  assert.equal(catalog['Question Bank'], 'Banca delle domande')
  assert.equal(catalog['Learning Space'], 'Spazio di apprendimento')
  assert.equal(catalog['New chat'], 'Nuova chat')
  assert.equal(catalog['Sign in'], 'Accedi')
  assert.equal(catalog['Save'], 'Salva')
  assert.equal(catalog['Cancel'], 'Annulla')
  assert.equal(catalog['Retry'], 'Riprova')
})

test('every catalog names Italian by its endonym', () => {
  for (const locale of fs.readdirSync(localesRoot).filter(name =>
    fs.existsSync(path.join(localesRoot, name, 'app.json'))
  )) {
    assert.equal(readCatalog(locale)['language.italian'], 'Italiano', locale)
  }
})
