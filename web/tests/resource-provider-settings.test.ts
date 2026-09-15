import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'

const readWebFile = (...parts: string[]) => readFileSync(path.join(process.cwd(), ...parts), 'utf8')

test('resource providers are exposed in the unified chat settings navigation', () => {
  const nav = readWebFile('features/settings/navigation/settings-nav.ts')
  const chatIndex = nav.indexOf('const CHAT_CHILDREN')
  const attachmentIndex = nav.indexOf('key: "attachments"', chatIndex)
  const providerIndex = nav.indexOf('key: "resource-providers"', chatIndex)
  const endIndex = nav.indexOf('];', chatIndex)

  assert.ok(chatIndex >= 0)
  assert.ok(attachmentIndex >= 0)
  assert.ok(providerIndex > attachmentIndex)
  assert.ok(providerIndex < endIndex)
  assert.match(nav, /href: "\/settings#resource-providers"/)
  assert.match(nav, /label: \{ zh: "资源提供方", en: "Resource Providers" \}/)
})

test('resource provider settings load on demand in the chat category', () => {
  const chat = readWebFile('features/settings/sections/ChatSettingsSection.tsx')

  assert.match(chat, /import\(['"]\.\/ResourceProvidersSettingsSection['"]\)/)
  assert.match(chat, /key: "resource-providers"/)
})

test('resource provider settings use the provider state endpoints safely', () => {
  const section = readWebFile('features/settings/sections/ResourceProvidersSettingsSection.tsx')

  assert.match(section, /apiUrl\(['"]\/api\/capabilities\/resource-providers['"]\)/)
  assert.match(
    section,
    /apiUrl\(`\/api\/capabilities\/resource-providers\/\$\{encodeURIComponent\(name\)\}\/state`\)/
  )
  assert.match(section, /method:\s*['"]PUT['"]/)
  assert.match(section, /JSON\.stringify\(\{ enabled \}\)/)
  assert.match(section, /setProviders\(snapshot\)/)
  assert.match(section, /disabled=\{pending\.size > 0\}/)
  assert.match(section, /providers\.length === 0/)
})

test('resource provider copy is complete and translated', () => {
  const section = readWebFile('features/settings/sections/ResourceProvidersSettingsSection.tsx')
  const en = JSON.parse(readWebFile('locales', 'en', 'app.json')) as Record<string, string>
  const zh = JSON.parse(readWebFile('locales', 'zh', 'app.json')) as Record<string, string>

  const keys = [
    'Resource Providers',
    'Control which learning-resource providers answer bounded lookups. Disabled providers stay registered and keep their configuration.',
    'Unexpected resource provider response.',
    'Failed to load resource providers.',
    'Failed to save resource provider state.',
    'Loading resource providers...',
    'Installed providers',
    'Changes take effect for new lookups immediately and persist across restarts.',
    'No resource providers are registered.',
    'Toggle {{name}}',
  ]
  const missing = keys.filter(key => !(key in en) || !(key in zh))
  const untranslated = keys.filter(key => zh[key] === en[key] && !/^[\d\s{}n·-]*$/.test(en[key]))

  assert.deepEqual(missing, [])
  assert.deepEqual(untranslated, [])
  for (const key of keys) {
    assert.ok(
      section.includes(`'${key}'`) || section.includes(`"${key}"`),
      `settings source should use copy key: ${key}`
    )
  }
})
