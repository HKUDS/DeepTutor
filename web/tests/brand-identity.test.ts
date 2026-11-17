import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

/**
 * Guards `DECISIONS.md` D-01: the product's **visible** identity is «درسیار»,
 * while every internal identifier stays `deeptutor`.
 *
 * The line matters in both directions. A reader must never meet "DeepTutor" in
 * the UI, and an operator must never find that `deeptutor init`, `DEEPTUTOR_HOME`
 * or an import path changed because the brand did. These tests hold both ends.
 */

function webRoot(): string {
  let dir = __dirname
  for (let i = 0; i < 8; i++) {
    if (fs.existsSync(path.join(dir, 'app')) && fs.existsSync(path.join(dir, 'lib/brand.ts'))) return dir
    dir = path.dirname(dir)
  }
  throw new Error('could not locate the web root')
}

const ROOT = webRoot()
const brand = fs.readFileSync(path.join(ROOT, 'lib/brand.ts'), 'utf8')
const en = JSON.parse(fs.readFileSync(path.join(ROOT, 'locales/en/app.json'), 'utf8')) as Record<string, string>

test('the brand module owns the displayed name', () => {
  assert.match(brand, /PRODUCT_NAME_FA\s*=\s*"درسیار"/)
  assert.match(brand, /PRODUCT_NAME_LATIN\s*=\s*"Darsyar"/)
  assert.match(brand, /export function productName/)
})

test('the document title and description carry the new brand', () => {
  const layout = fs.readFileSync(path.join(ROOT, 'app/layout.tsx'), 'utf8')
  assert.match(layout, /title:\s*PRODUCT_NAME_FA/)
  assert.match(layout, /description:\s*PRODUCT_TAGLINE/)
  // no literal upstream name left in the metadata block
  const meta = layout.slice(layout.indexOf('export const metadata'))
  assert.doesNotMatch(meta, /"DeepTutor"/)
})

test('no user-visible value still says DeepTutor', () => {
  // Keys are lookup handles and are allowed to keep the English sentence they
  // were written with; only what renders is brand copy.
  const offenders = Object.entries(en)
    .filter(([key, value]) => value !== key && /\bDeepTutor\b/.test(value))
    // Two exemptions, both about the *installation* rather than the product:
    // the upstream repository link, and the setup prompt an operator pastes
    // into their own agent. D-01 keeps internal names and attribution.
    .filter(([, value]) => !/github\.com|HKUDS|DeepTutor installation/.test(value))
    .map(([key, value]) => `${key} => ${value}`)
  assert.deepEqual(offenders, [])
})

test('every locale bundle is free of the old visible name', () => {
  // The English bundle carries the Persian wordmark; Latin-script bundles carry
  // the Latin one, so a French sentence never mixes scripts. Either way the old
  // name is gone from what renders.
  const bundles = fs
    .readdirSync(path.join(ROOT, 'locales'))
    .filter((lang) => fs.existsSync(path.join(ROOT, 'locales', lang, 'app.json')))
  assert.ok(bundles.length >= 14, `expected the full bundle set, found ${bundles.length}`)
  const offenders: string[] = []
  for (const lang of bundles) {
    const catalog = JSON.parse(
      fs.readFileSync(path.join(ROOT, 'locales', lang, 'app.json'), 'utf8'),
    ) as Record<string, string>
    for (const [key, value] of Object.entries(catalog)) {
      if (typeof value !== 'string' || value === key) continue
      if (!/\bDeepTutor\b/.test(value)) continue
      // Same two installation-level exemptions as the English check.
      if (/github\.com|HKUDS|DeepTutor installation/.test(value)) continue
      offenders.push(`${lang}: ${key} => ${value}`)
    }
  }
  assert.deepEqual(offenders, [])
})

test('the auth screens name the product from the brand module', () => {
  for (const page of ['app/(auth)/login/page.tsx', 'app/(auth)/register/page.tsx']) {
    const source = fs.readFileSync(path.join(ROOT, page), 'utf8')
    assert.match(source, /productName\(/, page)
    assert.doesNotMatch(source, />\s*DeepTutor\s*</, page)
  }
})

test('internal identity is untouched', () => {
  // The published package, the CLI verb, the runtime home and the env prefix are
  // the contract operators depend on. D-01 forbids renaming them here.
  const pyproject = fs.readFileSync(path.join(ROOT, '..', 'pyproject.toml'), 'utf8')
  assert.match(pyproject, /name\s*=\s*"deeptutor"/)
  const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8')) as {
    scripts: Record<string, string>
  }
  assert.ok(Object.keys(pkg.scripts).includes('build'))
  assert.ok(fs.existsSync(path.join(ROOT, '..', 'deeptutor')), 'python package directory must keep its name')
})
