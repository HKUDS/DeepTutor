import { expect, it } from 'vitest'
import { ensureLanguage, initI18n } from '@/i18n/init'

it('looks up natural-language keys that contain a colon as whole keys', async () => {
  const i18n = initI18n()
  await ensureLanguage('zh')
  const en = i18n.getFixedT('en', 'app')
  const zh = i18n.getFixedT('zh', 'app')
  expect(en('Query:')).toBe('Query:')
  expect(en('http://localhost:8080')).toBe('http://localhost:8080')
  expect(zh('Query:')).toBe('问题：')
  expect(zh('Conversations:')).toBe('对话列表：')
})
