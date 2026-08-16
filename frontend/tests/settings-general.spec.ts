import { test, expect, Page } from '@playwright/test'
import { mockDialogApi } from './dialog-api'

async function openHome(page: Page) {
  await mockDialogApi(page)
  await page.addInitScript(() => {
    if (!sessionStorage.getItem('trae:settings-init')) {
      localStorage.setItem('trae:theme', 'dark')
      localStorage.removeItem('trae:language')
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

test.describe('通用设置', () => {
  test('账号菜单打开通用设置弹层', async ({ page }) => {
    await openHome(page)
    await openSettings(page)
    await expect(page.locator('#dt-settings-title')).toHaveText('通用')
    await expect(page.locator('.dtSettingsProduct')).toHaveText('DeepTutor')
    await expect(page.locator('.dtSettingsNavItem.is-active')).toContainText('通用')
    await expect(page.locator('.dtSettingsSection').first()).toHaveText('基础设置')
    await expect(page.locator('.dtSettingsSection').nth(1)).toHaveText('偏好设置')
    await expect(page.getByRole('switch', { name: '语音转录快捷键' })).toBeVisible()
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

    await page.getByRole('button', { name: '语言' }).click()
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

  test('偏好控件可改并写入 localStorage', async ({ page }) => {
    await openHome(page)
    await openSettings(page)

    await page.getByRole('switch', { name: '语音转录快捷键' }).click()
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
    expect(parsed.voiceShortcut.enabled).toBe(false)
    expect(parsed.localLinkOpen).toBe('builtin')
    expect(parsed.artifactPath).toBe('~/Documents/DeepTutor')

    await page.reload()
    await page.waitForSelector('.app-root')
    await page.locator('.accountTrigger-y5IeNi').click()
    await page.locator('.accountMenuItem-NXEKcd').filter({ hasText: '设置' }).click()
    await expect(page.getByRole('switch', { name: '语音转录快捷键' })).toHaveAttribute('aria-checked', 'false')
    await expect(page.getByRole('button', { name: '本地链接的默认打开方式' })).toContainText('内置浏览器')
    await expect(page.locator('.dtSettingsPathValue')).toHaveText('~/Documents/DeepTutor')
  })

  test('Escape 关闭设置弹层', async ({ page }) => {
    await openHome(page)
    await openSettings(page)
    await page.keyboard.press('Escape')
    await expect(page.locator('.dtSettings[role="dialog"]')).toHaveCount(0)
  })
})
