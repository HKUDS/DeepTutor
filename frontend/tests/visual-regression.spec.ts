import { test, expect, Page } from '@playwright/test'
import path from 'path'
import fs from 'fs'
import { VIEWPORT, DPR, THEME, setupAppState, waitForStableRender } from './test-utils'

const SNAPSHOT_DIR = path.resolve(__dirname, '.snapshots')
const MHTML_DIR = path.resolve(__dirname, '..')

type StateConfig = {
  name: string
  mhtml: string
  view: 'chat' | 'new-task' | 'automation' | 'marketplace'
  sidebarOpen: boolean
  statusOpen: boolean
  description: string
  theme?: 'light' | 'dark'
  action?: (page: Page) => Promise<void>
}

const STATES: StateConfig[] = [
  {
    name: 'L1-left-middle-right',
    mhtml: '左栏+中栏+右栏.mhtml',
    view: 'chat',
    sidebarOpen: true,
    statusOpen: true,
    description: '三栏布局 (左栏+中栏+右栏)',
  },
  {
    name: 'L2-left-middle',
    mhtml: '左栏+中栏.mhtml',
    view: 'chat',
    sidebarOpen: true,
    statusOpen: false,
    description: '两栏布局 (左栏+中栏)',
  },
  {
    name: 'L3-middle',
    mhtml: '中栏.mhtml',
    view: 'chat',
    sidebarOpen: false,
    statusOpen: false,
    description: '单栏布局 (仅中栏)',
  },
  {
    name: 'L4-middle-right',
    mhtml: '中栏+右栏.mhtml',
    view: 'chat',
    sidebarOpen: false,
    statusOpen: true,
    description: '两栏布局 (中栏+右栏)',
  },
  {
    name: 'S1-new-task',
    mhtml: '新建任务.mhtml',
    view: 'new-task',
    sidebarOpen: true,
    statusOpen: false,
    description: '新建任务页面',
  },
  {
    name: 'S2-automation',
    mhtml: '自动化.mhtml',
    view: 'automation',
    sidebarOpen: true,
    statusOpen: false,
    description: '学习空间页面',
  },
  {
    name: 'S3-marketplace',
    mhtml: '插件市场.mhtml',
    view: 'marketplace',
    sidebarOpen: true,
    statusOpen: false,
    description: '插件市场页面',
  },
  {
    name: 'S4-plugin-detail',
    mhtml: '插件市场-插件详情.mhtml',
    view: 'marketplace',
    sidebarOpen: true,
    statusOpen: false,
    description: '插件详情弹窗',
    action: async (page: Page) => {
      await page.waitForSelector('.pluginCard-cq4jH5', { timeout: 10000 })
      await page.click('.pluginCard-cq4jH5:first-child')
      await page.waitForTimeout(500)
    },
  },
]

beforeAll(async () => {
  if (!fs.existsSync(SNAPSHOT_DIR)) {
    fs.mkdirSync(SNAPSHOT_DIR, { recursive: true })
  }
})

for (const state of STATES) {
  test.describe(`${state.description} (${state.name})`, () => {
    test('should match baseline screenshot', async ({ page }) => {
      const baselinePath = path.join(SNAPSHOT_DIR, `${state.name}-baseline.png`)
      const actualPath = path.join(SNAPSHOT_DIR, `${state.name}-actual.png`)

      if (process.env.UPDATE_SNAPSHOTS === '1' || !fs.existsSync(baselinePath)) {
        test.skip(!process.env.UPDATE_SNAPSHOTS && !fs.existsSync(baselinePath), 
          'Baseline not found. Run with UPDATE_SNAPSHOTS=1 to generate from MHTML.')
      }

      await setupAppState(page, {
        sidebarOpen: state.sidebarOpen,
        statusOpen: state.statusOpen,
        view: state.view,
        theme: state.theme ?? THEME,
      })

      if (state.action) {
        await state.action(page)
      }

      await waitForStableRender(page)

      await page.screenshot({
        path: actualPath,
        fullPage: false,
      })

      const baseline = fs.readFileSync(baselinePath)
      const actual = fs.readFileSync(actualPath)

      expect(actual).toEqual(baseline)
    })
  })
}

test.describe('Generate baselines from MHTML', () => {
  test('generate baseline screenshots from MHTML files', async ({ page }) => {
    const generateBaseline = async (state: StateConfig) => {
      const mhtmlPath = path.join(MHTML_DIR, state.mhtml)
      if (!fs.existsSync(mhtmlPath)) {
        console.warn(`MHTML not found: ${state.mhtml}`)
        return
      }

      const baselinePath = path.join(SNAPSHOT_DIR, `${state.name}-baseline.png`)

      await page.goto('about:blank')
      const mhtmlContent = fs.readFileSync(mhtmlPath, 'utf-8')

      await page.evaluate((html: string) => {
        document.open()
        document.write(html)
        document.close()
      }, mhtmlContent)

      await page.waitForTimeout(500)

      await page.screenshot({
        path: baselinePath,
        fullPage: false,
      })

      console.log(`Generated baseline: ${state.name}`)
    }

    for (const state of STATES) {
      await generateBaseline(state)
    }
  })
})
