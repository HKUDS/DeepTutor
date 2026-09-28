import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import ts from 'typescript'

const root = process.cwd()

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(file)
    return entry.name.endsWith('.tsx') ? [file] : []
  })
}

function attribute(
  node: ts.JsxOpeningElement | ts.JsxSelfClosingElement,
  name: string
): ts.JsxAttribute | undefined {
  return node.attributes.properties.find(
    (property): property is ts.JsxAttribute =>
      ts.isJsxAttribute(property) && property.name.getText() === name
  )
}

test('interactive native title hints must use the shared Tooltip', () => {
  const violations: string[] = []
  for (const sourceRoot of ['app', 'components', 'context', 'features', 'hooks', 'lib', 'shared']) {
    for (const file of sourceFiles(path.join(root, sourceRoot))) {
      const relative = path.relative(root, file).split(path.sep).join('/')
      const source = ts.createSourceFile(
        file,
        readFileSync(file, 'utf8'),
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.TSX
      )
      const nextLinkNames = new Set(
        source.statements
          .filter((statement): statement is ts.ImportDeclaration => ts.isImportDeclaration(statement))
          .filter(
            statement =>
              ts.isStringLiteral(statement.moduleSpecifier) &&
              statement.moduleSpecifier.text === 'next/link'
          )
          .map(statement => statement.importClause?.name?.text)
          .filter((name): name is string => Boolean(name))
      )
      const visit = (node: ts.Node) => {
        if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
          const tag = node.tagName.getText(source)
          const role = attribute(node, 'role')?.initializer?.getText(source) ?? ''
          const interactive =
            tag === 'button' ||
            tag === 'a' ||
            nextLinkNames.has(tag) ||
            (/^[a-z]/.test(tag) &&
              (['onClick', 'onMouseDown', 'onPointerDown', 'tabIndex'].some(name =>
                attribute(node, name)
              ) ||
                /\b(button|separator)\b/.test(role)))
          if (interactive && attribute(node, 'title')) {
            const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1
            violations.push(`${relative}:${line}`)
          }
        }
        ts.forEachChild(node, visit)
      }
      visit(source)
    }
  }
  assert.deepEqual(
    violations,
    [],
    'Replace interactive native title hints with @/shared/ui/Tooltip and an accessible name'
  )
})
