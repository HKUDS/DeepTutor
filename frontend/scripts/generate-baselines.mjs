import { writeFileSync, existsSync, mkdirSync, readFileSync } from 'fs'
import { join, resolve } from 'path'
import puppeteer from 'puppeteer'

const ROOT = resolve(import.meta.dirname, '..')
const MHTML_DIR = ROOT
const SNAPSHOT_DIR = join(ROOT, 'tests', '.snapshots')

const VIEWPORT = { width: 1440, height: 900 }
const DPR = 2

const STATES = [
  { name: 'L1-left-middle-right', mhtml: '左栏+中栏+右栏.mhtml' },
  { name: 'L2-left-middle', mhtml: '左栏+中栏.mhtml' },
  { name: 'L3-middle', mhtml: '中栏.mhtml' },
  { name: 'L4-middle-right', mhtml: '中栏+右栏.mhtml' },
  { name: 'S1-new-task', mhtml: '新建任务.mhtml' },
  { name: 'S2-automation', mhtml: '自动化.mhtml' },
  { name: 'S3-marketplace', mhtml: '插件市场.mhtml' },
  { name: 'S4-plugin-detail', mhtml: '插件市场-插件详情.mhtml' },
]

async function generateBaseline(browser, state) {
  const mhtmlPath = join(MHTML_DIR, state.mhtml)
  const baselinePath = join(SNAPSHOT_DIR, `${state.name}-baseline.png`)

  if (!existsSync(mhtmlPath)) {
    console.warn(`MHTML not found: ${state.mhtml}`)
    return
  }

  console.log(`Processing ${state.name} from ${state.mhtml}...`)

  const page = await browser.newPage()
  await page.setViewport({ ...VIEWPORT, deviceScaleFactor: DPR })

  try {
    const fileUrl = `file://${mhtmlPath}`
    await page.goto(fileUrl, { waitUntil: 'load', timeout: 15000 })
    await new Promise(r => setTimeout(r, 1500))

    await page.screenshot({
      path: baselinePath,
      clip: { x: 0, y: 0, width: VIEWPORT.width, height: VIEWPORT.height },
    })

    console.log(`  -> Generated: ${baselinePath}`)
  } catch (err) {
    console.error(`  -> Error: ${err.message}`)
  } finally {
    await page.close()
  }
}

async function main() {
  if (!existsSync(SNAPSHOT_DIR)) {
    mkdirSync(SNAPSHOT_DIR, { recursive: true })
  }

  console.log('Launching browser...')
  const browser = await puppeteer.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
    headless: true,
  })

  console.log('Generating baseline screenshots from MHTML...\n')

  for (const state of STATES) {
    await generateBaseline(browser, state)
  }

  await browser.close()
  console.log('\nDone! Baseline screenshots generated.')
}

main().catch(console.error)
