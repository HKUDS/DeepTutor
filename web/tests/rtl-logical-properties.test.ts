import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

/**
 * Guards the RTL / logical-property conversion (Phase 1, step 1.3).
 *
 * The conversion itself was a codemod over ~700 class tokens; these tests are
 * what stops it from silently rotting back. They also encode the three ways the
 * codemod was caught doing real damage, so the same mistakes cannot return:
 *
 *   1. JSX props that merely *contain* a direction word (`side="right"`,
 *      `align="right"`, BlockNote's `textAlignment: 'left'`) are component API
 *      values, not CSS. Rewriting them breaks the type of the owning component.
 *   2. Prose, comments and LaTeX command tables ("left", "right") are English
 *      words. Rewriting them changes what the app says and what it parses.
 *   3. Splitting an edge across two utilities (`border-l-[3px]` +
 *      `border-l-emerald-500`) must move *both* halves, or the colour lands on
 *      the opposite edge in RTL.
 */

function webRoot(): string {
  let dir = __dirname
  for (let i = 0; i < 8; i++) {
    if (fs.existsSync(path.join(dir, 'app')) && fs.existsSync(path.join(dir, 'i18n'))) return dir
    dir = path.dirname(dir)
  }
  throw new Error('could not locate the web root')
}

const ROOT = webRoot()
const SOURCE_DIRS = ['app', 'components', 'features']

interface SourceFile {
  path: string
  rel: string
  text: string
}

function sourceFiles(): SourceFile[] {
  const out: SourceFile[] = []
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === 'node_modules' || entry.name === '.next') continue
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (/\.tsx?$/.test(entry.name)) {
        out.push({
          path: full,
          rel: path.relative(ROOT, full).replaceAll('\\', '/'),
          text: fs.readFileSync(full, 'utf8'),
        })
      }
    }
  }
  for (const dir of SOURCE_DIRS) {
    const full = path.join(ROOT, dir)
    if (fs.existsSync(full)) walk(full)
  }
  return out
}

function cssFiles(): SourceFile[] {
  const out: SourceFile[] = []
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (entry.name.endsWith('.css')) {
        out.push({
          path: full,
          rel: path.relative(ROOT, full).replaceAll('\\', '/'),
          text: fs.readFileSync(full, 'utf8'),
        })
      }
    }
  }
  for (const dir of ['app', 'components', 'features']) {
    const full = path.join(ROOT, dir)
    if (fs.existsSync(full)) walk(full)
  }
  return out
}

/** A Tailwind directional utility, with variants and a leading `-`. */
const DIRECTIONAL = /(?<![\w-])((?:[a-z0-9_\-/[\]]+:)*)(-?)(ml|mr|pl|pr|left|right|border-l|border-r)(-(?:\[[^\]\s]+\]|[0-9][\w./[\]%-]*|auto|full|px))(?![\\w-])/g

const SOURCE = sourceFiles()

test('no class string still uses a physical inline-start/end utility', () => {
  // Only strings that are demonstrably class lists are inspected: a prose or
  // code string in this repo legitimately contains "left" (LaTeX tables).
  const offenders: string[] = []
  for (const file of SOURCE) {
    for (const match of file.text.matchAll(/["'`]([^"'`\n]{0,4000})["'`]/g)) {
      const body = match[1]
      if (!/(?:^|\s)(?:flex|grid|block|inline|items-|justify-|gap-|px-|py-|w-|h-|text-|bg-|border|rounded|absolute|relative)/.test(body)) {
        continue
      }
      for (const hit of body.matchAll(DIRECTIONAL)) {
        offenders.push(`${file.rel}: ${hit[0]}`)
      }
    }
  }
  assert.deepEqual(offenders, [])
})

test('component props keep their own direction vocabulary', () => {
  // These three are component API surfaces, not CSS. `TooltipSide` is
  // top/right/bottom/left; `align` is left/right; BlockNote's textAlignment is
  // left/center/right. A logical name there does not type-check.
  const offenders: string[] = []
  for (const file of SOURCE) {
    for (const pattern of [
      /side=\{?["'](?:start|end)["']/g,
      /align=\{?["'](?:start|end)["']/g,
      /align\s*=\s*["'](?:start|end)["']/g,
      /textAlignment:\s*["'](?:start|end)["']/g,
    ]) {
      for (const hit of file.text.matchAll(pattern)) {
        offenders.push(`${file.rel}: ${hit[0]}`)
      }
    }
  }
  assert.deepEqual(offenders, [])
})

test('comments and prose still speak the product language', () => {
  // A codemod that rewrites inside comments silently changes documentation and
  // user-facing strings. Spot-check the words that were at risk.
  const offenders: string[] = []
  for (const file of SOURCE) {
    for (const line of file.text.split('\n')) {
      const trimmed = line.trim()
      const isComment = trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')
      if (!isComment) continue
      // "start"/"end" are perfectly ordinary English; the failure mode is a
      // comment that now describes CSS with logical names it never had.
      if (/\b(?:ms|me|ps|pe)-\d/.test(trimmed) || /inline-start|inline-end/.test(trimmed)) {
        offenders.push(`${file.rel}: ${trimmed}`)
      }
    }
  }
  assert.deepEqual(offenders, [])
})

test('an edge is never split across physical and logical halves', () => {
  // `border-s-[3px] border-l-emerald-500` would draw a 3px start border in one
  // colour and a full-width left border in another. Both halves must agree.
  const offenders: string[] = []
  for (const file of SOURCE) {
    for (const match of file.text.matchAll(/["'`]([^"'`\n]{0,4000})["'`]/g)) {
      const tokens = match[1].split(/\s+/)
      const hasLogicalEdge = tokens.some(token => /^border-[se](?:-|$)/.test(token))
      if (!hasLogicalEdge) continue
      const physical = tokens.filter(token => /^border-[lr](?:-|$)/.test(token))
      if (physical.length) offenders.push(`${file.rel}: ${physical.join(' ')}`)
    }
  }
  assert.deepEqual(offenders, [])
})

test('stylesheets express insets and padding on the inline axis', () => {
  const offenders: string[] = []
  for (const file of cssFiles()) {
    for (const [index, line] of file.text.split('\n').entries()) {
      if (/^\s*(margin|padding|border)-(?:left|right)\s*:/.test(line)) {
        offenders.push(`${file.rel}:${index + 1} ${line.trim()}`)
      }
    }
  }
  assert.deepEqual(offenders, [])
})

test('the locale declares direction and the document publishes it', () => {
  const languages = fs.readFileSync(path.join(ROOT, 'i18n/languages.ts'), 'utf8')
  assert.match(languages, /RTL_LANGUAGES/)
  assert.match(languages, /new Set<AppLanguage>\(\["fa"\]\)/)
  assert.match(languages, /export function textDirection/)
  assert.match(languages, /export function regionalLocale/)

  const provider = fs.readFileSync(path.join(ROOT, 'i18n/I18nProvider.tsx'), 'utf8')
  assert.match(provider, /root\.lang =/)
  assert.match(provider, /root\.dir =/)
})
