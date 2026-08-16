import { test, expect, Page } from '@playwright/test'
import { mockDialogApi } from './dialog-api'

async function openHome(page: Page) {
  await mockDialogApi(page)
  await page.addInitScript(() => {
    if (!sessionStorage.getItem('trae:settings-init')) {
      localStorage.setItem('trae:theme', 'dark')
      localStorage.removeItem('trae:language')
      localStorage.removeItem('deeptutor:response-language')
      localStorage.removeItem('deeptutor:voice-autoplay')
      localStorage.removeItem('deeptutor:chat-timeout')
      localStorage.removeItem('deeptutor:general-settings')
      sessionStorage.setItem('trae:settings-init', '1')
    }
    localStorage.setItem('trae:sidebarOpen', '1')
    localStorage.setItem('trae:statusOpen', '0')
    sessionStorage.setItem('trae:view', 'chat')
  })
  await page.goto('/')
  await page.waitForSelector('.app-root')
}

async function openSettings(page: Page) {
  await page.locator('.accountTrigger-y5IeNi').click()
  await page.locator('.accountMenuItem-NXEKcd').filter({ hasText: '设置' }).click()
  await expect(page.locator('.dtSettings[role="dialog"]')).toBeVisible()
}

async function openChatPane(page: Page) {
  await page.locator('.dtSettingsNavItem').filter({ hasText: '对话与工具' }).click()
  await expect(page.locator('#dt-settings-title')).toHaveText('对话与工具')
}

test.describe('通用设置', () => {
  test('账号菜单打开通用设置弹层', async ({ page }) => {
    await openHome(page)
    await openSettings(page)
    await expect(page.locator('#dt-settings-title')).toHaveText('通用')
    await expect(page.locator('.dtSettingsProduct')).toHaveText('Lumen')
    await expect(page.locator('.dtSettingsNavItem.is-active')).toContainText('通用')
    await expect(page.locator('.dtSettingsSection').nth(0)).toHaveText('基础设置')
    await expect(page.locator('.dtSettingsSection').nth(1)).toHaveText('偏好设置')
    await expect(page.getByRole('button', { name: '主题' })).toBeVisible()
    await expect(page.getByRole('switch', { name: '回复自动朗读' })).toHaveCount(0)
    await expect(page.getByRole('switch', { name: '头脑风暴' })).toHaveCount(0)
    await expect(page.locator('.dtSettingsNavItem').filter({ hasText: '对话与工具' })).toBeVisible()
    await openChatPane(page)
    await expect(page.locator('.dtSettingsSection').nth(0)).toHaveText('回复')
    await expect(page.locator('.dtSettingsSection').nth(1)).toHaveText('可选工具')
    await expect(page.getByRole('switch', { name: '回复自动朗读' })).toBeVisible()
    await expect(page.getByRole('button', { name: '模型回复语言' })).toBeVisible()
    await expect(page.getByRole('button', { name: '对话等待超时' })).toBeVisible()
    await expect(page.getByRole('switch', { name: '头脑风暴' })).toBeVisible()
    await page.locator('.dtSettingsClose').click()
    await expect(page.locator('.dtSettings[role="dialog"]')).toHaveCount(0)
  })

  test('主题与语言可改并保存', async ({ page }) => {
    await openHome(page)
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await openSettings(page)

    await page.getByRole('button', { name: '主题' }).click()
    await page.getByRole('option', { name: '亮色' }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')

    await page.getByRole('button', { name: '语言', exact: true }).click()
    await page.getByRole('option', { name: 'English' }).click()
    await expect(page.locator('#dt-settings-title')).toHaveText('General')
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')

    await page.locator('.dtSettingsClose').click()
    await page.reload()
    await page.waitForSelector('.app-root')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')
    await page.locator('.accountTrigger-y5IeNi').click()
    await expect(page.locator('.accountMenuValue-iTOf2H').filter({ hasText: 'English' })).toBeVisible()
  })

  test('回复语言、自动朗读、超时与工具可改并保存', async ({ page }) => {
    await openHome(page)

    const saved = {
      responseLanguage: 'zh',
      autoplay: false,
      timeout: 180,
      tools: ['brainstorm', 'web_search', 'paper_search', 'reason'],
    }
    await page.route('**/api/v1/settings/ui', async (route) => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON() as { response_language?: string }
        if (body.response_language) saved.responseLanguage = body.response_language
        await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ response_language: saved.responseLanguage }),
      })
    })
    await page.route('**/api/v1/settings/voice-autoplay', async (route) => {
      saved.autoplay = Boolean((route.request().postDataJSON() as { voice_autoplay?: boolean }).voice_autoplay)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ voice_autoplay: saved.autoplay }),
      })
    })
    await page.route('**/api/v1/settings/chat-response-timeout', async (route) => {
      saved.timeout = Number((route.request().postDataJSON() as { chat_response_timeout?: number }).chat_response_timeout)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ chat_response_timeout: saved.timeout }),
      })
    })
    await page.route('**/api/v1/settings/enabled-tools', async (route) => {
      saved.tools = (route.request().postDataJSON() as { enabled_tools?: string[] }).enabled_tools ?? saved.tools
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ enabled_optional_tools: saved.tools }),
      })
    })
    await page.route('**/api/v1/tools**', async (route) => {
      const catalog = [
        { name: 'brainstorm', zh: '头脑风暴' },
        { name: 'web_search', zh: '网页搜索' },
        { name: 'paper_search', zh: '论文搜索' },
        { name: 'reason', zh: '深度推理' },
      ]
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          tools: catalog.map((tool) => ({
            name: tool.name,
            toggleable: true,
            enabled: saved.tools.includes(tool.name),
            description_i18n: { zh: tool.zh },
          })),
          enabled_optional_tools: saved.tools,
        }),
      })
    })
    await page.route('**/api/v1/settings', async (route) => {
      if (route.request().url().includes('/settings/')) {
        await route.fallback()
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ui: {
            response_language: saved.responseLanguage,
            voice_autoplay: saved.autoplay,
            chat_response_timeout: saved.timeout,
          },
        }),
      })
    })

    await openSettings(page)
    await openChatPane(page)
    await page.getByRole('button', { name: '模型回复语言' }).click()
    await page.getByRole('option', { name: 'English' }).click()
    await page.getByRole('switch', { name: '回复自动朗读' }).click()
    await page.getByRole('button', { name: '对话等待超时' }).click()
    await page.getByRole('option', { name: '5 分钟' }).click()
    await page.getByRole('switch', { name: '网页搜索' }).click()

    await expect(page.getByRole('button', { name: '模型回复语言' })).toContainText('English')
    await expect(page.getByRole('switch', { name: '回复自动朗读' })).toHaveAttribute('aria-checked', 'true')
    await expect(page.getByRole('button', { name: '对话等待超时' })).toContainText('5 分钟')
    await expect(page.getByRole('switch', { name: '网页搜索' })).toHaveAttribute('aria-checked', 'false')

    const storedLang = await page.evaluate(() => localStorage.getItem('deeptutor:response-language'))
    const storedPlay = await page.evaluate(() => localStorage.getItem('deeptutor:voice-autoplay'))
    const storedTimeout = await page.evaluate(() => localStorage.getItem('deeptutor:chat-timeout'))
    expect(storedLang).toBe('en')
    expect(storedPlay).toBe('1')
    expect(storedTimeout).toBe('300')

    await page.reload()
    await page.waitForSelector('.app-root')
    await page.locator('.accountTrigger-y5IeNi').click()
    await page.locator('.accountMenuItem-NXEKcd').filter({ hasText: '设置' }).click()
    await openChatPane(page)
    await expect(page.getByRole('button', { name: '模型回复语言' })).toContainText('English')
    await expect(page.getByRole('switch', { name: '回复自动朗读' })).toHaveAttribute('aria-checked', 'true')
    await expect(page.getByRole('button', { name: '对话等待超时' })).toContainText('5 分钟')
    await expect(page.getByRole('switch', { name: '网页搜索' })).toHaveAttribute('aria-checked', 'false')
  })

  test('偏好控件可改并写入 localStorage', async ({ page }) => {
    await openHome(page)
    await openSettings(page)

    await page.getByRole('button', { name: '本地链接的默认打开方式' }).click()
    await page.getByRole('option', { name: '内置浏览器' }).click()
    await page.locator('.dtSettingsPathBtn').click()
    const pathInput = page.locator('.dtSettingsPathInput')
    await expect(pathInput).toBeVisible()
    await pathInput.fill('~/Documents/DeepTutor')
    await pathInput.press('Enter')
    await expect(page.locator('.dtSettingsPathValue')).toHaveText('~/Documents/DeepTutor')

    const stored = await page.evaluate(() => localStorage.getItem('deeptutor:general-settings'))
    expect(stored).toBeTruthy()
    const parsed = JSON.parse(stored!)
    expect(parsed.localLinkOpen).toBe('builtin')
    expect(parsed.artifactPath).toBe('~/Documents/DeepTutor')

    await page.reload()
    await page.waitForSelector('.app-root')
    await page.locator('.accountTrigger-y5IeNi').click()
    await page.locator('.accountMenuItem-NXEKcd').filter({ hasText: '设置' }).click()
    await expect(page.getByRole('button', { name: '本地链接的默认打开方式' })).toContainText('内置浏览器')
    await expect(page.locator('.dtSettingsPathValue')).toHaveText('~/Documents/DeepTutor')
  })

  test('每个下拉和工具开关都完整可见', async ({ page }) => {
    await openHome(page)
    await openSettings(page)

    const assertAllVisible = async (role: 'option' | 'switch', names: string[]) => {
      for (const name of names) {
        const item = page.getByRole(role, { name, exact: true })
        await item.scrollIntoViewIfNeeded()
        await expect(item).toBeVisible()
        const box = await item.boundingBox()
        expect(box, name).toBeTruthy()
        expect(box!.width, name).toBeGreaterThan(16)
        expect(box!.height, name).toBeGreaterThan(12)
        const clip = await item.evaluate((el) => {
          const r = el.getBoundingClientRect()
          const mid = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
          return !(mid && (el === mid || el.contains(mid) || mid.contains(el)))
        })
        expect(clip, `${name} 被挡住`).toBe(false)
      }
    }

    await page.getByRole('button', { name: '主题' }).click()
    await assertAllVisible('option', ['亮色', '暗色'])
    await page.getByRole('option', { name: '暗色' }).click()

    await page.getByRole('button', { name: '语言', exact: true }).click()
    await assertAllVisible('option', ['简体中文', 'English'])
    await page.getByRole('option', { name: '简体中文' }).click()

    await page.getByRole('button', { name: '本地链接的默认打开方式' }).click()
    await assertAllVisible('option', ['始终询问', '内置浏览器', '系统默认浏览器'])
    await page.getByRole('option', { name: '始终询问' }).click()

    await page.locator('.dtSettingsPathBtn').click()
    await expect(page.locator('.dtSettingsPathInput')).toBeVisible()
    await page.locator('.dtSettingsPathInput').press('Escape')

    await openChatPane(page)
    await page.getByRole('button', { name: '模型回复语言' }).click()
    await assertAllVisible('option', ['简体中文', 'English'])
    await page.getByRole('option', { name: '简体中文' }).click()

    await page.getByRole('button', { name: '对话等待超时' }).click()
    await assertAllVisible('option', ['30 秒', '1 分钟', '3 分钟', '5 分钟', '10 分钟', '30 分钟'])
    await page.getByRole('option', { name: '3 分钟' }).click()

    await assertAllVisible('switch', ['回复自动朗读', '头脑风暴', '网页搜索', '论文搜索', '深度推理'])
    await page.getByRole('switch', { name: '回复自动朗读' }).click()
    await page.getByRole('switch', { name: '头脑风暴' }).click()
    await page.getByRole('switch', { name: '网页搜索' }).click()
    await page.getByRole('switch', { name: '论文搜索' }).click()
    await page.getByRole('switch', { name: '深度推理' }).click()
  })

  test('Escape 关闭设置弹层', async ({ page }) => {
    await openHome(page)
    await openSettings(page)
    await page.keyboard.press('Escape')
    await expect(page.locator('.dtSettings[role="dialog"]')).toHaveCount(0)
  })
})
