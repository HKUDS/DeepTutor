#!/usr/bin/env node
/**
 * Measure TraeWork / Askora composer visual + interaction contract.
 * Does NOT click send, does NOT create TraeWork sessions.
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const WS = process.env.CDP_WS
const TARGET = process.argv[2] || 'traework-session'
const OUT_DIR = path.resolve('scripts')
const SHOT_DIR = path.resolve('screenshots/composer-probe')

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

function box(r) {
  if (!r) return null
  return {
    x: Math.round(r.x * 10) / 10,
    y: Math.round(r.y * 10) / 10,
    w: Math.round(r.width * 10) / 10,
    h: Math.round(r.height * 10) / 10,
  }
}

const VISUAL_PROPS = [
  'display', 'position', 'boxSizing',
  'width', 'height', 'minHeight', 'maxHeight', 'minWidth', 'maxWidth',
  'marginTop', 'marginRight', 'marginBottom', 'marginLeft',
  'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
  'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
  'borderTopStyle', 'borderRightStyle', 'borderBottomStyle', 'borderLeftStyle',
  'borderTopColor', 'borderRightColor', 'borderBottomColor', 'borderLeftColor',
  'borderTopLeftRadius', 'borderTopRightRadius', 'borderBottomRightRadius', 'borderBottomLeftRadius',
  'backgroundColor', 'backgroundImage', 'boxShadow', 'outline', 'outlineOffset',
  'color', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing',
  'opacity', 'visibility', 'overflow', 'overflowX', 'overflowY',
  'flex', 'flexDirection', 'alignItems', 'justifyContent', 'gap',
  'zIndex', 'pointerEvents', 'cursor', 'userSelect', 'whiteSpace', 'wordBreak',
  'transform', 'filter',
]

async function dumpState(page, label) {
  return page.evaluate(({ labelInner, props }) => {
    const pick = (el) => {
      if (!el) return null
      const s = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      const out = {
        tag: el.tagName,
        id: el.id || '',
        className: String(el.className || '').slice(0, 280),
        role: el.getAttribute?.('role') || '',
        aria: {
          label: el.getAttribute?.('aria-label'),
          disabled: el.getAttribute?.('aria-disabled'),
          expanded: el.getAttribute?.('aria-expanded'),
          haspopup: el.getAttribute?.('aria-haspopup'),
          multiline: el.getAttribute?.('aria-multiline'),
        },
        disabled: !!el.disabled,
        contentEditable: el.getAttribute?.('contenteditable') || el.contentEditable || '',
        text: (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 180),
        html: (el.innerHTML || '').slice(0, 500),
        childCount: el.childElementCount,
        childClasses: [...el.children].slice(0, 12).map((c) =>
          `${c.tagName}.${String(c.className || '').slice(0, 80)}`,
        ),
        attrs: [...(el.attributes || [])].map((a) => [a.name, String(a.value).slice(0, 160)]),
        box: {
          x: Math.round(r.x * 10) / 10,
          y: Math.round(r.y * 10) / 10,
          w: Math.round(r.width * 10) / 10,
          h: Math.round(r.height * 10) / 10,
        },
        style: {},
      }
      for (const p of props) out.style[p] = s[p]
      return out
    }

    const q = (sel) => document.querySelector(sel)
    const qa = (sel) => [...document.querySelectorAll(sel)]

    const container = q('.chat-input-v2-container')
    const editorPart = q('.chat-input-v2-editor-part')
    const wrapper = q('.chat-input-v2-input-box-wrapper')
    const editable = q('.chat-input-v2-input-box-editable, [contenteditable="true"][role="textbox"]')
    const placeholder = q('.chat-input-v2-placeholder')
    const lower = q('.chat-input-v2-editor-part-lower-content')
    const left = q('.chat-input-v2-editor-part-lower__left')
    const right = q('.chat-input-v2-editor-part-lower__right')
    const send = q('.chat-input-v2-send-button')
    const mic = q('.rtcVoicePluginButton')
    const plus = q('.messageInputToolbarIconBtn')
    const plugin = q('.messageInputPluginToolbar')
    const model = q('.core-model-select-trigger')
    const messageInput = q('.messageInputContainer')
    const overlay = q('.chat-input-v2-slot-overlay')
    const header = q('.chat-input-v2-slot-header')
    const upper = q('.chat-input-v2-upper-area')

    const toolbarButtons = qa(
      '.chat-input-v2-editor-part-lower-content button, .chat-input-v2-slot-toolbar-right button',
    ).map((el) => ({
      className: String(el.className || '').slice(0, 160),
      aria: el.getAttribute('aria-label'),
      disabled: !!el.disabled,
      html: el.innerHTML.slice(0, 280),
      box: (() => {
        const r = el.getBoundingClientRect()
        return { x: Math.round(r.x * 10) / 10, y: Math.round(r.y * 10) / 10, w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10 }
      })(),
      bg: getComputedStyle(el).backgroundColor,
      color: getComputedStyle(el).color,
      radius: getComputedStyle(el).borderRadius,
    }))

    return {
      label: labelInner,
      url: location.href,
      title: document.title,
      viewport: { w: innerWidth, h: innerHeight, dpr: devicePixelRatio },
      theme: document.documentElement.getAttribute('data-theme') || document.documentElement.className,
      active: {
        tag: document.activeElement?.tagName,
        className: String(document.activeElement?.className || '').slice(0, 200),
      },
      parts: {
        messageInput: pick(messageInput),
        container: pick(container),
        editorPart: pick(editorPart),
        upper: pick(upper),
        header: pick(header),
        wrapper: pick(wrapper),
        placeholder: pick(placeholder),
        editable: pick(editable),
        lower: pick(lower),
        left: pick(left),
        right: pick(right),
        plus: pick(plus),
        plugin: pick(plugin),
        model: pick(model),
        mic: pick(mic),
        send: pick(send),
        overlay: pick(overlay),
      },
      toolbarButtons,
      outerHTML: (editorPart || container || messageInput)?.outerHTML?.slice(0, 8000) || null,
    }
  }, { labelInner: label, props: VISUAL_PROPS })
}

async function shot(page, name) {
  fs.mkdirSync(SHOT_DIR, { recursive: true })
  const file = path.join(SHOT_DIR, `${name}.png`)
  const target = page.locator('.chat-input-v2-editor-part, .messageInputContainer, .chat-input-v2-container').first()
  if (await target.count()) {
    await target.screenshot({ path: file })
  } else {
    await page.screenshot({ path: file })
  }
  return file
}

async function restoreComposer(page) {
  const editable = page.locator('.chat-input-v2-input-box-editable, [contenteditable="true"][role="textbox"]').first()
  if (!(await editable.count())) return
  await editable.click({ timeout: 3000 }).catch(() => {})
  await page.keyboard.press('Meta+A')
  await page.keyboard.press('Backspace')
  await sleep(120)
}

async function measureSurface(page, prefix) {
  const result = { prefix, url: page.url(), title: await page.title(), states: {} }

  await page.waitForSelector('.chat-input-v2-container, .chat-input-v2-input-box-editable', { timeout: 15000 })
  await sleep(400)

  // 1. idle as-is
  result.states.idle = await dumpState(page, `${prefix}-idle`)
  result.shots = { idle: await shot(page, `${prefix}-idle`) }

  // 2. click wrapper to focus (empty if possible)
  await restoreComposer(page)
  const wrapper = page.locator('.chat-input-v2-input-box-wrapper').first()
  if (await wrapper.count()) {
    await wrapper.click({ position: { x: 20, y: 20 } }).catch(() => {})
  } else {
    await page.locator('.chat-input-v2-input-box-editable').first().click().catch(() => {})
  }
  await sleep(200)
  result.states.focusedEmpty = await dumpState(page, `${prefix}-focused-empty`)
  result.shots.focusedEmpty = await shot(page, `${prefix}-focused-empty`)

  // 3. type locally — never send
  const editable = page.locator('.chat-input-v2-input-box-editable, [contenteditable="true"][role="textbox"]').first()
  await editable.click()
  await page.keyboard.type('Hello Askora probe', { delay: 12 })
  await sleep(200)
  result.states.typed = await dumpState(page, `${prefix}-typed`)
  result.shots.typed = await shot(page, `${prefix}-typed`)

  // 4. Shift+Enter
  await page.keyboard.down('Shift')
  await page.keyboard.press('Enter')
  await page.keyboard.up('Shift')
  await page.keyboard.type('line2', { delay: 10 })
  await sleep(200)
  result.states.afterShiftEnter = await dumpState(page, `${prefix}-shift-enter`)
  result.shots.afterShiftEnter = await shot(page, `${prefix}-shift-enter`)

  // 5. blur
  await page.locator('body').click({ position: { x: 8, y: 8 } }).catch(() => {})
  await sleep(200)
  result.states.blurredWithText = await dumpState(page, `${prefix}-blur`)
  result.shots.blurredWithText = await shot(page, `${prefix}-blur`)

  // restore so we do not leave draft that could be sent accidentally
  await restoreComposer(page)
  await page.keyboard.press('Escape').catch(() => {})
  result.states.restored = await dumpState(page, `${prefix}-restored`)

  return result
}

async function main() {
  const browser = await chromium.connectOverCDP(WS || 'http://[::1]:9222')
  const context = browser.contexts()[0]
  const pages = context.pages()

  let page
  if (TARGET === 'traework-session') {
    page = pages.find((p) => p.url().includes('work.trae.ai/session')) || pages.find((p) => p.url().includes('work.trae.ai'))
    if (!page) throw new Error('no TraeWork session tab')
    await page.bringToFront()
  } else if (TARGET === 'traework-home') {
    page = pages.find((p) => /^https:\/\/work\.trae\.ai\/?(\?.*)?$/.test(p.url()))
    if (!page) {
      page = await context.newPage()
      await page.goto('https://work.trae.ai/', { waitUntil: 'domcontentloaded', timeout: 30000 })
    }
    await page.bringToFront()
    await sleep(800)
    // click 新建对话 / 新建任务 if needed, but do not create via network if already on home
    const onHome = /work\.trae\.ai\/?(\?|$)/.test(page.url()) && !page.url().includes('/session/')
    if (!onHome) {
      await page.goto('https://work.trae.ai/', { waitUntil: 'domcontentloaded', timeout: 30000 })
      await sleep(1000)
    }
  } else if (TARGET === 'askora-home') {
    page = pages.find((p) => p.url().includes('127.0.0.1:5173')) || pages.find((p) => p.url().includes('localhost:5173'))
    if (!page) {
      page = await context.newPage()
      await page.goto('http://127.0.0.1:5173/', { waitUntil: 'domcontentloaded' })
    }
    await page.bringToFront()
    await page.evaluate(() => {
      localStorage.setItem('trae:sidebarOpen', '1')
      localStorage.setItem('trae:statusOpen', '0')
      localStorage.setItem('trae:theme', 'dark')
      sessionStorage.setItem('trae:view', 'chat')
    })
    const newBtn = page.locator('.navItem-r4wswG').filter({ hasText: '新建对话' })
    if (await newBtn.count()) await newBtn.click()
    await sleep(400)
  } else if (TARGET === 'askora-session') {
    page = pages.find((p) => p.url().includes('127.0.0.1:5173')) || pages.find((p) => p.url().includes('localhost:5173'))
    if (!page) {
      page = await context.newPage()
      await page.goto('http://127.0.0.1:5173/', { waitUntil: 'domcontentloaded' })
    }
    await page.bringToFront()
    await page.evaluate(() => {
      localStorage.setItem('trae:sidebarOpen', '1')
      localStorage.setItem('trae:statusOpen', '0')
      localStorage.setItem('trae:theme', 'dark')
      sessionStorage.setItem('trae:view', 'chat')
    })
    // click first existing session in sidebar if any
    const item = page.locator('.taskItem').first()
    if (await item.count()) {
      await item.click()
      await sleep(400)
    } else {
      await page.evaluate(() => {
        const sessions = [{
          id: 'probe-existing',
          backendId: null,
          label: '已有对话探测',
          time: '12:00',
          messages: [
            {
              id: 'u1',
              role: 'user',
              author: 'Xike',
              time: '12:00',
              blocks: [{ type: 'text', content: '探测用已有对话' }],
            },
            {
              id: 'a1',
              role: 'assistant',
              author: 'Askora',
              time: '12:00',
              blocks: [{ type: 'text', content: '这是探测回复，不是学习证据。' }],
            },
          ],
        }]
        localStorage.setItem('askora:sessions', JSON.stringify(sessions))
        localStorage.setItem('askora:selectedSession', 'probe-existing')
        sessionStorage.setItem('trae:view', 'chat')
      })
      await page.reload({ waitUntil: 'domcontentloaded' })
      await sleep(600)
      const seeded = page.locator('.taskItem').first()
      if (await seeded.count()) await seeded.click()
      await sleep(300)
    }
  } else {
    throw new Error(`unknown target ${TARGET}`)
  }

  const measured = await measureSurface(page, TARGET)
  const out = path.join(OUT_DIR, `probe-composer-contract.${TARGET}.json`)
  fs.writeFileSync(out, JSON.stringify(measured, null, 2))
  console.log('wrote', out)
  console.log('url', measured.url)
  console.log('idle send', measured.states.idle?.parts?.send?.className)
  console.log('typed send', measured.states.typed?.parts?.send?.className)
  console.log('editor box idle', measured.states.idle?.parts?.editorPart?.box)
  console.log('editor box typed', measured.states.typed?.parts?.editorPart?.box)
  // do not browser.close(); detach so node can exit
  process.exit(0)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
