import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import ts from 'typescript'

// Inline `{ zh, en }` copy is allowed only when the English side goes through t(), so
// every locale can translate it (docs-for-dev/I18N.md). These checks keep the remaining
// inline copy on that path.

const root = process.cwd()
const SOURCE_ROOTS = ['app', 'components', 'context', 'features', 'hooks', 'lib', 'shared']
const LOCALES = ['en', 'zh', 'de', 'fr', 'ja', 'pl', 'pt', 'tr', 'uk', 'vi']
// Legacy settings editors with no importers, pending removal.
const UNUSED_FILES = new Set([
  'components/settings/ConnectionsEditor.tsx',
  'components/settings/ModelCards.tsx',
  'components/settings/ServiceConfigEditor.tsx',
])
// Chinese/English literals that are deliberately not catalog copy.
const LITERAL_EXCEPTIONS = new Set([
  // Sample sentence spoken by the selected voice, not interface text.
  'components/settings/VoicePreviewPanel.tsx',
  // Default name stored with a new model entry.
  'features/settings/store/SettingsStore.tsx',
])
// Translator helpers that take a Chinese and an English argument.
const PAIR_HELPERS = new Set(['tr', 'text'])
const CJK = /[\u4e00-\u9fff]/

const catalogs = LOCALES.map(locale => ({
  locale,
  keys: new Set(
    Object.keys(
      JSON.parse(readFileSync(path.join(root, 'locales', locale, 'app.json'), 'utf8')) as Record<
        string,
        string
      >
    )
  ),
}))

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(directory, entry.name)
    if (entry.isDirectory()) return entry.name === 'node_modules' ? [] : sourceFiles(file)
    return /\.tsx?$/.test(entry.name) && !entry.name.endsWith('.d.ts') ? [file] : []
  })
}

function parsedSources() {
  return SOURCE_ROOTS.flatMap(sourceRoot => sourceFiles(path.join(root, sourceRoot))).map(file => {
    const relative = path.relative(root, file).split(path.sep).join('/')
    const source = ts.createSourceFile(
      file,
      readFileSync(file, 'utf8'),
      ts.ScriptTarget.Latest,
      true,
      file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
    )
    return { relative, source }
  })
}

const sources = parsedSources()

function walk(node: ts.Node, visit: (node: ts.Node) => void) {
  visit(node)
  ts.forEachChild(node, child => walk(child, visit))
}

function stringValue(node: ts.Node | undefined): string | undefined {
  if (!node) return undefined
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text
  return undefined
}

function propertyName(node: ts.ObjectLiteralElementLike): string | undefined {
  if (!ts.isPropertyAssignment(node)) return undefined
  return ts.isIdentifier(node.name) || ts.isStringLiteral(node.name) ? node.name.text : undefined
}

function where(source: ts.SourceFile, relative: string, node: ts.Node): string {
  const { line } = source.getLineAndCharacterOfPosition(node.getStart())
  return `${relative}:${line + 1}`
}

test('a zh branch never picks the English text without t()', () => {
  const violations: string[] = []
  for (const { relative, source } of sources) {
    if (UNUSED_FILES.has(relative)) continue
    walk(source, node => {
      if (!ts.isConditionalExpression(node)) return
      const whenTrue = node.whenTrue
      const whenFalse = node.whenFalse
      const picksZh =
        (ts.isPropertyAccessExpression(whenTrue) && whenTrue.name.text === 'zh') ||
        (ts.isElementAccessExpression(whenTrue) && stringValue(whenTrue.argumentExpression) === 'zh')
      const picksEn =
        (ts.isPropertyAccessExpression(whenFalse) && whenFalse.name.text === 'en') ||
        (ts.isElementAccessExpression(whenFalse) && stringValue(whenFalse.argumentExpression) === 'en')
      if (picksZh && picksEn) violations.push(where(source, relative, node))
    })
  }
  assert.deepEqual(violations, [], `use t(<english>) for the non-Chinese branch:\n${violations.join('\n')}`)
})

function isLiteral(node: ts.Node): boolean {
  return ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateExpression(node)
}

test('a zh branch never pairs Chinese text with a raw English literal', () => {
  const violations: string[] = []
  for (const { relative, source } of sources) {
    if (UNUSED_FILES.has(relative) || LITERAL_EXCEPTIONS.has(relative)) continue
    walk(source, node => {
      if (!ts.isConditionalExpression(node)) return
      const { whenTrue, whenFalse } = node
      if (!isLiteral(whenTrue) || !isLiteral(whenFalse)) return
      if (!CJK.test(whenTrue.getText()) || CJK.test(whenFalse.getText())) return
      if (!/[A-Za-z]{2,}/.test(whenFalse.getText())) return
      violations.push(where(source, relative, node))
    })
  }
  assert.deepEqual(violations, [], `use t(<english>) for the non-Chinese branch:\n${violations.join('\n')}`)
})

test('dates follow the interface language, not a zh/en switch', () => {
  const violations: string[] = []
  for (const { relative, source } of sources) {
    walk(source, node => {
      if (!ts.isConditionalExpression(node)) return
      const whenTrue = stringValue(node.whenTrue)
      const whenFalse = stringValue(node.whenFalse)
      if (whenTrue === 'zh-CN' && whenFalse !== undefined && /^en(-US)?$/.test(whenFalse)) {
        violations.push(where(source, relative, node))
      }
    })
  }
  assert.deepEqual(violations, [], `use getLocale() from lib/datetime:\n${violations.join('\n')}`)
})

test('inline English copy next to Chinese copy exists in every catalog', () => {
  const missing: string[] = []
  const check = (english: string, source: ts.SourceFile, relative: string, node: ts.Node) => {
    if (!english.trim() || CJK.test(english)) return
    for (const { locale, keys } of catalogs) {
      if (!keys.has(english)) missing.push(`${where(source, relative, node)} ${locale}: ${JSON.stringify(english)}`)
    }
  }
  for (const { relative, source } of sources) {
    if (UNUSED_FILES.has(relative)) continue
    walk(source, node => {
      if (ts.isObjectLiteralExpression(node)) {
        const props = new Map(
          node.properties
            .map(property => [propertyName(property), property] as const)
            .filter((entry): entry is [string, ts.PropertyAssignment] => Boolean(entry[0]))
        )
        const zh = stringValue(props.get('zh')?.initializer)
        const en = stringValue(props.get('en')?.initializer)
        if (zh !== undefined && en !== undefined && CJK.test(zh)) check(en, source, relative, node)
        if (props.get('en') && ts.isTemplateExpression(props.get('en')!.initializer)) {
          missing.push(`${where(source, relative, node)}: template literal en text cannot be a catalog key`)
        }
      }
      // (en, cn) and (cn, en) helper calls such as text('Export', '导出') or tr('导出', 'Export').
      if (
        ts.isCallExpression(node) &&
        node.arguments.length >= 2 &&
        ts.isIdentifier(node.expression) &&
        PAIR_HELPERS.has(node.expression.text)
      ) {
        const first = stringValue(node.arguments[0])
        const second = stringValue(node.arguments[1])
        if (first === undefined || second === undefined) return
        if (CJK.test(first) && !CJK.test(second)) check(second, source, relative, node)
        else if (CJK.test(second) && !CJK.test(first)) check(first, source, relative, node)
      }
    })
  }
  assert.deepEqual(missing, [], `add these keys to every catalog:\n${missing.slice(0, 40).join('\n')}`)
})
