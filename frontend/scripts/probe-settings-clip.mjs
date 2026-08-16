#!/usr/bin/env node
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const CDP = process.env.CDP_URL || 'http://[::1]:9222'
const OUT = path.resolve('frontend/scripts/probe-settings-clip')
const VIEW = { width: 1440, height: 900 }

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)) }

async function setFixedWindow(page) {
  const session = await page.context().newCDPSession(page)
  const { windowId } = await session.send('Browser.getWindowForTarget')
  const before = await session.send('Browser.getWindowBounds', { windowId })
  await session.send('Browser.setWindowBounds', {
    windowId,
    bounds: { windowState: 'normal', width: VIEW.width, height: VIEW.height },
  })
  await page.setViewportSize(VIEW)
  await sleep(200)
  const after = await session.send('Browser.getWindowBounds', { windowId })
  const inner = await page.evaluate(() => ({ w: window.innerWidth, h: window.innerHeight }))
  return { before: before.bounds, after: after.bounds, inner }
}

async function visibility(page, role, names) {
  const rows = []
  for (const name of names) {
    const item = page.getByRole(role, { name, exact: true })
    const visible = await item.isVisible()
    const box = visible ? await item.boundingBox() : null
    const covered = visible ? await item.evaluate((el) => {
      const r = el.getBoundingClientRect()
      const mid = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
      return !(mid && (el === mid || el.contains(mid) || mid.contains(el)))
    }) : true
    rows.push({ name, visible, covered, box })
  }
  return rows
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await chromium.connectOverCDP(CDP)
  const page = browser.contexts().flatMap((c) => c.pages()).find((p) => p.url().includes('127.0.0.1:5174'))
  if (!page) throw new Error('DeepTutor tab not found')
  await page.bringToFront()
  const windowInfo = await setFixedWindow(page)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.accountTrigger-y5IeNi', { timeout: 15000 })
  await sleep(500)

  await page.locator('.accountTrigger-y5IeNi').click()
  await page.locator('.accountMenuItem-NXEKcd').filter({ hasText: '设置' }).click()
  await page.waitForSelector('.dtSettings[role="dialog"]')
  await sleep(200)

  const steps = []

  await page.getByRole('button', { name: '主题' }).click()
  await sleep(160)
  steps.push({ name: 'theme', items: await visibility(page, 'option', ['亮色', '暗色']) })
  await page.screenshot({ path: path.join(OUT, 'theme.png') })
  await page.getByRole('option', { name: '暗色' }).click()
  await sleep(120)
  await page.getByRole('button', { name: '主题' }).click()
  await page.getByRole('option', { name: '亮色' }).click()

  await page.getByRole('button', { name: '语言', exact: true }).click()
  await sleep(160)
  steps.push({ name: 'language', items: await visibility(page, 'option', ['简体中文', 'English']) })
  await page.screenshot({ path: path.join(OUT, 'language.png') })
  await page.getByRole('option', { name: '简体中文' }).click()

  await page.getByRole('button', { name: '本地链接的默认打开方式' }).click()
  await sleep(160)
  steps.push({ name: 'localLink', items: await visibility(page, 'option', ['始终询问', '内置浏览器', '系统默认浏览器']) })
  await page.screenshot({ path: path.join(OUT, 'localLink.png') })
  await page.getByRole('option', { name: '始终询问' }).click()

  await page.locator('.dtSettingsPathBtn').click()
  await sleep(160)
  const pathVisible = await page.locator('.dtSettingsPathInput').isVisible()
  steps.push({ name: 'path', items: [{ name: 'path-input', visible: pathVisible, covered: false }] })
  await page.screenshot({ path: path.join(OUT, 'path.png') })
  await page.locator('.dtSettingsPathInput').press('Escape')

  await page.locator('.dtSettingsNavItem').filter({ hasText: '对话与工具' }).click()
  await sleep(160)
  await page.screenshot({ path: path.join(OUT, 'chat-pane.png') })

  await page.getByRole('button', { name: '模型回复语言' }).click()
  await sleep(160)
  steps.push({ name: 'replyLanguage', items: await visibility(page, 'option', ['简体中文', 'English']) })
  await page.screenshot({ path: path.join(OUT, 'reply-language.png') })
  await page.getByRole('option', { name: '简体中文' }).click()

  await page.getByRole('button', { name: '对话等待超时' }).click()
  await sleep(160)
  steps.push({ name: 'timeout', items: await visibility(page, 'option', ['30 秒', '1 分钟', '3 分钟', '5 分钟', '10 分钟', '30 分钟']) })
  await page.screenshot({ path: path.join(OUT, 'timeout.png') })
  await page.getByRole('option', { name: '3 分钟' }).click()

  await page.getByRole('switch', { name: '回复自动朗读' }).click()
  await sleep(80)
  await page.getByRole('switch', { name: '回复自动朗读' }).click()

  const failed = steps.flatMap((s) => s.items.filter((i) => !i.visible || i.covered).map((i) => ({ step: s.name, ...i })))
  const summary = { windowInfo, steps, failed }
  fs.writeFileSync(`${OUT}.json`, JSON.stringify(summary, null, 2))
  console.log(JSON.stringify(summary, null, 2))
  if (failed.length) process.exit(1)
  process.exit(0)
}

main().catch((e) => { console.error(e); process.exit(1) })
