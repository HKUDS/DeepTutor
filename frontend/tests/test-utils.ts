import { Page, BrowserContext } from '@playwright/test'

export const VIEWPORT = { width: 1440, height: 900 }
export const DPR = 2
export const THEME = 'light'

export async function setupAppState(page: Page, config: {
  sidebarOpen?: boolean
  statusOpen?: boolean
  view?: 'chat' | 'new-task' | 'automation' | 'marketplace'
  theme?: 'light' | 'dark'
} = {}) {
  const sidebarOpen = config.sidebarOpen ?? true
  const statusOpen = config.statusOpen ?? true
  const view = config.view ?? 'chat'
  const theme = config.theme ?? THEME

  await page.route('**/*', async (route) => {
    const url = route.request().url()
    if (url.includes('api.') || url.includes('font')) {
      await route.abort()
    } else {
      await route.continue()
    }
  })

  await page.addInitScript((state: typeof config) => {
    if (state.sidebarOpen !== undefined) {
      localStorage.setItem('trae:sidebarOpen', state.sidebarOpen ? '1' : '0')
    }
    if (state.statusOpen !== undefined) {
      localStorage.setItem('trae:statusOpen', state.statusOpen ? '1' : '0')
    }
    if (state.theme !== undefined) {
      localStorage.setItem('trae:theme', state.theme)
    }
    if (state.view) {
      sessionStorage.setItem('trae:view', state.view)
    }
  }, { sidebarOpen, statusOpen, theme, view })

  await page.goto('/')
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(500)
}

export async function waitForStableRender(page: Page) {
  await page.waitForTimeout(300)
  await page.waitForSelector('.app-root', { state: 'attached', timeout: 5000 })
  await page.waitForTimeout(200)
}

export async function captureScreenshot(page: Page, name: string) {
  await page.screenshot({
    path: `tests/.snapshots/${name}.png`,
    fullPage: false,
  })
}

export function getSnapshotPath(name: string) {
  return `tests/.snapshots/${name}.png`
}
