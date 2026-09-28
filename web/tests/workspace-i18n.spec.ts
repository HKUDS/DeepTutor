import { expect, it } from 'vitest'
import { ensureLanguage, initI18n } from '@/i18n/init'
import common from '@/locales/zh/common.json'

it('loads all workspace resource translations in the runtime namespace', async () => {
  const i18n = initI18n()
  await ensureLanguage('zh')
  const t = i18n.getFixedT('zh', 'app')
  for (const key of Object.keys(common).filter(key => !key.startsWith('language.') && !key.startsWith('common.'))) {
    expect(i18n.exists(key, { lng: 'zh', ns: 'app' }), key).toBe(true)
  }
  expect(t('Assigned resources')).toBe('分配资源')
  expect(t('MCP services')).toBe('MCP 服务')
  expect(t('{{count}} resources selected', { count: 2 })).toBe('已选择 2 项资源')
})
