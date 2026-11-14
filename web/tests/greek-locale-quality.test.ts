import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

function findLocalesRoot(): string {
  let dir = __dirname
  for (let i = 0; i < 8; i++) {
    // The compiled test tree copies app.json only; the source tree also has common.json.
    const candidate = path.join(dir, 'locales', 'el', 'common.json')
    if (fs.existsSync(candidate)) return path.join(dir, 'locales')
    dir = path.dirname(dir)
  }
  throw new Error('could not locate locales/el/common.json')
}

const localesRoot = findLocalesRoot()
const readCatalog = (locale: string, file = 'app.json') =>
  JSON.parse(fs.readFileSync(path.join(localesRoot, locale, file), 'utf8')) as Record<
    string,
    string
  >
const catalog = readCatalog('el')
const lowered = Object.values(catalog).join('\n').toLocaleLowerCase('el')

// \b only knows ASCII word characters and would split Greek words.
function containsWord(text: string, word: string): boolean {
  const escaped = word.toLocaleLowerCase('el').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(?<![\\p{L}\\p{M}\\p{N}_])${escaped}(?![\\p{L}\\p{M}\\p{N}_])`, 'u').test(text)
}

// Greek inflects nouns and verbs, so a rejected stem must match every ending.
function containsStem(text: string, stem: string): boolean {
  const escaped = stem.toLocaleLowerCase('el').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(?<![\\p{L}\\p{M}\\p{N}_])${escaped}`, 'u').test(text)
}

test('Greek common.json mirrors the English keys', () => {
  assert.deepEqual(
    Object.keys(readCatalog('el', 'common.json')).sort(),
    Object.keys(readCatalog('en', 'common.json')).sort()
  )
})

test('Greek activity labels describe actions in progress', () => {
  assert.equal(catalog['Reading skill'], 'Ανάγνωση δεξιότητας')
  assert.equal(catalog['Reading source'], 'Ανάγνωση πηγής')
  assert.equal(catalog['Writing file'], 'Εγγραφή αρχείου')
  assert.equal(catalog['Listing files'], 'Απαρίθμηση αρχείων')
  assert.equal(catalog['Saving memory'], 'Αποθήκευση μνήμης')
})

test('Greek UI keeps the product glossary', () => {
  assert.equal(catalog['Knowledge Base'], 'Γνωσιακή βάση')
  assert.equal(catalog['Knowledge Bases'], 'Γνωσιακές βάσεις')
  assert.equal(catalog['Knowledge Point'], 'Σημείο ενότητας')
  assert.equal(catalog['Mastery Path'], 'Mastery Path')
  assert.equal(catalog['Guided Learning'], 'Καθοδηγούμενη μάθηση')
  assert.equal(catalog['Question Bank'], 'Τράπεζα ερωτήσεων')
  assert.equal(catalog['Learning Space'], 'Χώρος μάθησης')
  assert.equal(catalog['Partners'], 'Partners')
  assert.equal(catalog['Soul'], 'Soul')
  assert.equal(catalog['Learner'], 'Μαθητής')
  assert.equal(catalog['Upload'], 'Ανέβασμα')
  assert.equal(catalog['Immersive Reading'], 'Ανάγνωση με βοηθό')
  assert.equal(catalog['navigation.resources'], 'Προσωπικός χώρος')
  assert.equal(catalog['Providers'], 'Πάροχοι')
  assert.equal(catalog['Embedding models'], 'Μοντέλα embedding')
  // Keys kept from renamed features: the English value, not the key, is translated.
  assert.equal(catalog['Notebook'], 'Αγαπημένα')
  assert.equal(catalog['Co-Writer'], 'Σημειωματάριο')
  assert.equal(catalog['New chat'], 'Νέα συνομιλία')
  assert.equal(catalog['Sign in'], 'Σύνδεση')
  assert.equal(catalog['Save'], 'Αποθήκευση')
  assert.equal(catalog['Cancel'], 'Ακύρωση')
})

test('Greek UI keeps one term per concept', () => {
  // Variants that appeared while the catalog was translated in parallel passes,
  // plus common renderings the glossary rejects.
  const offGlossary = [
    'βάση γνώσης',
    'βάσεις γνώσης',
    'πράκτορ',
    'βάση γνώσεων',
    'βάσεις γνώσεων',
    'βάσης γνώσεων',
    'βάσεων γνώσεων',
    'γνωστικό στοιχεί',
    'γνωστικά στοιχεί',
    'διαδρομή κατάκτησης',
    'μεταφόρτωσ',
    'μεταφορτ',
    'εκπαιδευόμεν',
    'καθηλωτικ',
    'απαλοιφ',
    'πλευρική στήλ',
    'προτροπ',
    'σημείο γνώσης',
    'σημεία γνώσης',
    'εικονογράφημ',
    'σύντροφ',
    'δωμάτι',
    'ακύρωση αναίρεσης',
    'συνεδρίασ',
  ]
  for (const term of offGlossary) {
    assert.equal(containsStem(lowered, term), false, `Found off-glossary term: ${term}`)
  }
  // Whole words only: these stems also start valid words (εκπαιδευτικός, ψυχολογία).
  for (const word of ['εκπαιδευτής', 'εκπαιδευτή', 'ψυχή', 'ψυχής', 'ψυχές']) {
    assert.equal(containsWord(lowered, word), false, `Found off-glossary term: ${word}`)
  }
})

test('Greek UI addresses the reader with the polite plural', () => {
  for (const informal of [
    'σου',
    'εσύ',
    'σένα',
    'επίλεξε',
    'διάλεξε',
    'πάτα',
    'δοκίμασε',
    'πρόσθεσε',
    'άνοιξε',
  ]) {
    assert.equal(containsWord(lowered, informal), false, `Found informal address: ${informal}`)
  }
})

test('Greek UI uses the Greek question mark', () => {
  const text = Object.values(catalog).join('\n')
  assert.equal(
    /[Ͱ-Ͽἀ-῿][»)]?\?/u.test(text),
    false,
    'Found "?" after Greek text; use ";"'
  )
})

test('every catalog names Greek by its endonym', () => {
  for (const locale of fs.readdirSync(localesRoot).filter(name =>
    fs.existsSync(path.join(localesRoot, name, 'app.json'))
  )) {
    assert.equal(readCatalog(locale)['language.greek'], 'Ελληνικά', locale)
  }
})
