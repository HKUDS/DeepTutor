import { writeFileSync, existsSync, mkdirSync, readFileSync } from 'fs'
import { join, resolve } from 'path'
import pixelmatch from 'pixelmatch'
import { PNG } from 'pngjs'
import puppeteer from 'puppeteer'

const ROOT = resolve(import.meta.dirname, '..')
const SNAPSHOT_DIR = join(ROOT, 'tests', '.snapshots')
const RESULTS_DIR = join(ROOT, 'playwright-report', 'test-results')

const VIEWPORT = { width: 1440, height: 900 }
const DPR = 2
const THRESHOLD = 0.011

const STATES = [
  { name: 'L1-left-middle-right', mhtml: '左栏+中栏+右栏.mhtml', view: 'chat', sidebarOpen: true, statusOpen: true, theme: 'dark' },
  { name: 'L2-left-middle', mhtml: '左栏+中栏.mhtml', view: 'chat', sidebarOpen: true, statusOpen: false, theme: 'dark' },
  { name: 'L3-middle', mhtml: '中栏.mhtml', view: 'chat', sidebarOpen: false, statusOpen: false, theme: 'dark' },
  { name: 'L4-middle-right', mhtml: '中栏+右栏.mhtml', view: 'chat', sidebarOpen: false, statusOpen: true, theme: 'dark' },
  { name: 'S1-new-task', mhtml: '新建任务.mhtml', view: 'new-task', sidebarOpen: true, statusOpen: false, theme: 'dark' },
  { name: 'S2-automation', mhtml: '自动化.mhtml', view: 'automation', sidebarOpen: true, statusOpen: false, theme: 'dark' },
  { name: 'S3-marketplace', mhtml: '插件市场.mhtml', view: 'marketplace', sidebarOpen: true, statusOpen: false, theme: 'dark' },
  { name: 'S4-plugin-detail', mhtml: '插件市场-插件详情.mhtml', view: 'marketplace', sidebarOpen: true, statusOpen: false, skillTabClick: true, theme: 'dark' },
]

async function compareImages(baselinePath, actualPath, diffPath) {
  const baseline = PNG.sync.read(readFileSync(baselinePath))
  const actual = PNG.sync.read(readFileSync(actualPath))

  if (baseline.width !== actual.width || baseline.height !== actual.height) {
    console.warn(`  Size mismatch: baseline ${baseline.width}x${baseline.height} vs actual ${actual.width}x${actual.height}`)
    return 1
  }

  const diff = new PNG({ width: baseline.width, height: baseline.height })
  const numDiffPixels = pixelmatch(baseline.data, actual.data, diff.data, baseline.width, baseline.height, {
    tolerance: 0.05,
    includeAA: false,
  })

  writeFileSync(diffPath, PNG.sync.write(diff))

  const diffRatio = numDiffPixels / (baseline.width * baseline.height)
  return diffRatio
}

async function captureActual(browser, state) {
  const page = await browser.newPage()
  await page.setViewport({ ...VIEWPORT, deviceScaleFactor: DPR })

  await page.goto('http://localhost:5173', { waitUntil: 'load', timeout: 30000 })

  await page.evaluate((config) => {
    localStorage.setItem('trae:sidebarOpen', config.sidebarOpen ? '1' : '0')
    localStorage.setItem('trae:statusOpen', config.statusOpen ? '1' : '0')
    localStorage.setItem('trae:theme', config.theme || 'dark')
    sessionStorage.setItem('trae:view', config.view)
    return true
  }, {
    sidebarOpen: state.sidebarOpen,
    statusOpen: state.statusOpen,
    view: state.view,
    theme: state.theme || 'dark',
  })

  page.reload()
  await new Promise(r => setTimeout(r, 3000))

  if (state.clickPlugin) {
    try {
      await page.waitForSelector('.pluginCard-cq4jH5', { timeout: 10000 })
      await page.click('.pluginCard-cq4jH5:first-child')
      await new Promise(r => setTimeout(r, 500))
    } catch (e) {
      console.warn(`  Plugin card not found, skipping click`)
    }
  }

  if (state.skillTabClick) {
    try {
      await page.waitForSelector('.tabSlider-Ol2p3T', { timeout: 10000 })
      const tabs = await page.$$('.tabSlider-Ol2p3T button')
      if (tabs.length >= 2) {
        await tabs[1].click()
        await new Promise(r => setTimeout(r, 500))
      }
      await page.waitForSelector('.skillCard-ZYOuVS', { timeout: 10000 })
      await page.click('.skillCard-ZYOuVS:first-child')
      await new Promise(r => setTimeout(r, 500))
    } catch (e) {
      console.warn(`  Skill tab or card not found, skipping click`)
    }
  }

  await new Promise(r => setTimeout(r, 500))

  const actualPath = join(SNAPSHOT_DIR, `${state.name}-actual.png`)
  await page.screenshot({
    path: actualPath,
    clip: { x: 0, y: 0, width: VIEWPORT.width, height: VIEWPORT.height },
  })

  await page.close()
  return actualPath
}

async function main() {
  if (!existsSync(SNAPSHOT_DIR)) {
    mkdirSync(SNAPSHOT_DIR, { recursive: true })
  }
  if (!existsSync(RESULTS_DIR)) {
    mkdirSync(RESULTS_DIR, { recursive: true })
  }

  console.log('Launching browser for visual regression testing...')
  const browser = await puppeteer.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
    headless: true,
  })

  const results = []

  for (const state of STATES) {
    console.log(`\nTesting ${state.name}...`)

    const baselinePath = join(SNAPSHOT_DIR, `${state.name}-baseline.png`)
    const diffPath = join(SNAPSHOT_DIR, `${state.name}-diff.png`)

    if (!existsSync(baselinePath)) {
      console.warn(`  Baseline not found: ${baselinePath}`)
      results.push({ name: state.name, status: 'SKIP', diff: 0 })
      continue
    }

    try {
      const actualPath = await captureActual(browser, state)
      const diffRatio = await compareImages(baselinePath, actualPath, diffPath)
      const passed = diffRatio <= THRESHOLD

      console.log(`  Diff: ${(diffRatio * 100).toFixed(3)}% ${passed ? '✅ PASS' : '❌ FAIL'}`)
      results.push({ name: state.name, status: passed ? 'PASS' : 'FAIL', diff: diffRatio })
    } catch (err) {
      console.error(`  Error: ${err.message}`)
      results.push({ name: state.name, status: 'ERROR', diff: 0, error: err.message })
    }
  }

  await browser.close()

  console.log('\n' + '='.repeat(60))
  console.log('VISUAL REGRESSION RESULTS')
  console.log('='.repeat(60))

  const passed = results.filter(r => r.status === 'PASS').length
  const failed = results.filter(r => r.status === 'FAIL').length
  const skipped = results.filter(r => r.status === 'SKIP').length
  const errors = results.filter(r => r.status === 'ERROR').length

  for (const r of results) {
    const icon = r.status === 'PASS' ? '✅' : r.status === 'FAIL' ? '❌' : r.status === 'ERROR' ? '⚠️' : '⏭️'
    console.log(`  ${icon} ${r.name}: ${r.status}${r.diff ? ` (diff: ${(r.diff * 100).toFixed(3)}%)` : ''}`)
  }

  console.log(`\nSummary: ${passed} passed, ${failed} failed, ${skipped} skipped, ${errors} errors`)
  console.log(`Threshold: ${(THRESHOLD * 100).toFixed(1)}%`)

  if (failed > 0 || errors > 0) {
    process.exit(1)
  }
}

main().catch(err => {
  console.error('Fatal error:', err)
  process.exit(1)
})
