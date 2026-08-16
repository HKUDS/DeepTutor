#!/usr/bin/env node
/**
 * Attach to the already-running Chrome via CDP and probe TraeWork + Askora
 * chat input interaction. Does not launch or restart Chrome.
 */
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const OUT = path.resolve('scripts/probe-chat-input.result.json')
const WS = process.env.CDP_WS || 'ws://127.0.0.1:9222/devtools/browser/a995f278-25cf-4eaf-94c2-8278c3e3f1f0'
const TARGET = process.argv[2] || 'traework' // traework | askora

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

async function dumpComposer(page, label) {
  return page.evaluate((labelInner) => {
    const editable = document.querySelector(
      '.chat-input-v2-input-box-editable, [contenteditable="true"], textarea, [role="textbox"]',
    )
    const placeholder = document.querySelector('.chat-input-v2-placeholder')
    const send = document.querySelector(
      '.chat-input-v2-send-button, button[aria-label="发送"], button[aria-label*="Send"]',
    )
    const container = document.querySelector('.chat-input-v2-container')
    const overlay = document.querySelector('.chat-input-v2-slot-overlay')

    const cs = (el) => {
      if (!el) return null
      const s = getComputedStyle(el)
      return {
        display: s.display,
        visibility: s.visibility,
        pointerEvents: s.pointerEvents,
        zIndex: s.zIndex,
        opacity: s.opacity,
        userSelect: s.userSelect,
        position: s.position,
        overflow: s.overflow,
      }
    }

    const chain = []
    let n = editable
    let depth = 0
    while (n && depth < 14) {
      chain.push({
        tag: n.tagName,
        id: n.id || '',
        className: String(n.className || '').slice(0, 240),
        role: n.getAttribute?.('role') || '',
        contentEditable: n.getAttribute?.('contenteditable') || n.contentEditable || '',
        disabled: !!n.disabled,
        readOnly: !!n.readOnly,
        tabIndex: n.tabIndex,
      })
      n = n.parentElement
      depth += 1
    }

    return {
      label: labelInner,
      url: location.href,
      title: document.title,
      activeTag: document.activeElement?.tagName || null,
      activeClass: String(document.activeElement?.className || '').slice(0, 200),
      editable: editable && {
        tag: editable.tagName,
        className: String(editable.className || ''),
        role: editable.getAttribute('role'),
        contentEditable: editable.getAttribute('contenteditable') || editable.contentEditable,
        spellcheck: editable.spellcheck,
        ariaDisabled: editable.getAttribute('aria-disabled'),
        ariaReadonly: editable.getAttribute('aria-readonly'),
        ariaMultiline: editable.getAttribute('aria-multiline'),
        disabled: !!editable.disabled,
        readOnly: !!editable.readOnly,
        text: (editable.innerText || editable.textContent || '').slice(0, 400),
        html: (editable.innerHTML || '').slice(0, 500),
        childCount: editable.childNodes.length,
        childTags: [...editable.childNodes].map((c) =>
          c.nodeType === 1 ? c.tagName + '.' + String(c.className || '').slice(0, 80) : `#text:${(c.textContent || '').slice(0, 40)}`,
        ),
        attrs: [...editable.attributes].map((a) => [a.name, a.value.slice(0, 120)]),
        styleAttr: editable.getAttribute('style'),
        cs: cs(editable),
      },
      placeholder: placeholder && {
        text: placeholder.textContent,
        display: placeholder.style.display || getComputedStyle(placeholder).display,
        className: String(placeholder.className || ''),
        cs: cs(placeholder),
      },
      send: send && {
        tag: send.tagName,
        className: String(send.className || ''),
        ariaLabel: send.getAttribute('aria-label'),
        disabled: !!send.disabled,
        ariaDisabled: send.getAttribute('aria-disabled'),
        html: (send.innerHTML || '').slice(0, 300),
        cs: cs(send),
      },
      container: container && {
        className: String(container.className || ''),
        hasFocus: container.className.includes('has-focus'),
        empty: container.className.includes('--empty'),
        noFocus: container.className.includes('--no-focus'),
      },
      overlay: overlay && { className: String(overlay.className || ''), cs: cs(overlay) },
      chain,
    }
  }, label)
}

async function installObservers(page) {
  await page.evaluate(() => {
    const w = window
    w.__probe = {
      events: [],
      mutations: [],
      network: [],
      startedAt: Date.now(),
    }
    const interesting = [
      'click',
      'focus',
      'blur',
      'beforeinput',
      'input',
      'change',
      'keydown',
      'keyup',
      'keypress',
      'compositionstart',
      'compositionupdate',
      'compositionend',
    ]
    const rec = (e) => {
      const t = e.target
      const el = t && t.nodeType === 1 ? t : t?.parentElement
      const cls = String(el?.className || '')
      if (
        !cls.includes('chat-input') &&
        el?.getAttribute?.('role') !== 'textbox' &&
        el?.getAttribute?.('contenteditable') == null &&
        !cls.includes('send') &&
        e.type !== 'compositionstart' &&
        e.type !== 'compositionend'
      ) {
        if (!['keydown', 'keyup', 'beforeinput', 'input'].includes(e.type)) return
        if (!(el?.closest?.('.chat-input-v2-container, .messageInputContainer'))) return
      }
      w.__probe.events.push({
        t: Date.now() - w.__probe.startedAt,
        type: e.type,
        key: e.key,
        code: e.code,
        shift: e.shiftKey,
        meta: e.metaKey,
        ctrl: e.ctrlKey,
        isComposing: e.isComposing,
        inputType: e.inputType,
        data: e.data,
        tag: el?.tagName,
        className: cls.slice(0, 160),
        text: (el?.innerText || el?.textContent || '').slice(0, 80),
      })
      if (w.__probe.events.length > 400) w.__probe.events.shift()
    }
    interesting.forEach((type) => document.addEventListener(type, rec, true))

    const obs = new MutationObserver((muts) => {
      for (const m of muts) {
        const el = m.target
        const cls = String(el.className || '')
        if (
          !cls.includes('chat-input') &&
          !cls.includes('virtualized-message') &&
          !cls.includes('turn') &&
          !cls.includes('user-message')
        ) {
          continue
        }
        w.__probe.mutations.push({
          t: Date.now() - w.__probe.startedAt,
          type: m.type,
          attr: m.attributeName,
          className: cls.slice(0, 200),
          text: (el.textContent || '').slice(0, 80),
        })
        if (w.__probe.mutations.length > 200) w.__probe.mutations.shift()
      }
    })
    obs.observe(document.documentElement, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['class', 'style', 'disabled', 'aria-disabled', 'contenteditable'],
    })

    const origFetch = window.fetch
    window.fetch = function (...args) {
      const url = typeof args[0] === 'string' ? args[0] : args[0]?.url
      w.__probe.network.push({ t: Date.now() - w.__probe.startedAt, kind: 'fetch', url: String(url || '').slice(0, 240) })
      return origFetch.apply(this, args)
    }
    const OrigWS = window.WebSocket
    window.WebSocket = function (url, proto) {
      w.__probe.network.push({ t: Date.now() - w.__probe.startedAt, kind: 'ws-open', url: String(url || '').slice(0, 240) })
      return proto ? new OrigWS(url, proto) : new OrigWS(url)
    }
    window.WebSocket.prototype = OrigWS.prototype
    const OrigXHR = window.XMLHttpRequest
    const open = OrigXHR.prototype.open
    OrigXHR.prototype.open = function (method, url, ...rest) {
      w.__probe.network.push({ t: Date.now() - w.__probe.startedAt, kind: 'xhr', method, url: String(url || '').slice(0, 240) })
      return open.call(this, method, url, ...rest)
    }
  })
}

async function readObservers(page) {
  return page.evaluate(() => window.__probe || null)
}

async function clickNewConversation(page) {
  const clicked = await page.evaluate(() => {
    const candidates = [...document.querySelectorAll('[role="button"], button, .navItem-r4wswG, a')]
    const hit = candidates.find((el) => {
      const t = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').replace(/\s+/g, '')
      return t.includes('新建对话') || t.includes('新建任务') || t.includes('NewChat') || t.includes('New Task')
    })
    if (hit) {
      hit.click()
      return { ok: true, text: (hit.innerText || hit.getAttribute('aria-label') || '').slice(0, 80), className: String(hit.className || '').slice(0, 120) }
    }
    return { ok: false }
  })
  return clicked
}

async function probeTraeWork(page) {
  const result = { site: 'traework', steps: {} }
  result.initialUrl = page.url()
  result.initialTitle = await page.title()

  await installObservers(page)
  result.beforeNew = await dumpComposer(page, 'before-new')

  const clicked = await clickNewConversation(page)
  result.clickNew = clicked
  await sleep(800)
  result.afterNew = await dumpComposer(page, 'after-new')

  const editable = page.locator('.chat-input-v2-input-box-editable, [contenteditable="true"][role="textbox"]').first()
  await editable.click({ timeout: 5000 }).catch((e) => {
    result.focusError = String(e)
  })
  await sleep(200)
  result.afterFocus = await dumpComposer(page, 'after-focus')

  await page.keyboard.type('Hello TraeWork probe', { delay: 20 })
  await sleep(300)
  result.afterType = await dumpComposer(page, 'after-type')

  // Shift+Enter
  await page.keyboard.down('Shift')
  await page.keyboard.press('Enter')
  await page.keyboard.up('Shift')
  await sleep(200)
  result.afterShiftEnter = await dumpComposer(page, 'after-shift-enter')

  const send = page.locator('.chat-input-v2-send-button').first()
  const sendInfo = await send.evaluate((el) => ({
    className: el.className,
    disabled: el.disabled,
    box: el.getBoundingClientRect(),
  })).catch((e) => ({ error: String(e) }))
  result.sendBeforeClick = sendInfo

  const requests = []
  const onReq = (req) => {
    requests.push({
      t: Date.now(),
      method: req.method(),
      type: req.resourceType(),
      url: req.url().slice(0, 260),
    })
  }
  page.on('request', onReq)

  await send.click({ timeout: 5000 }).catch(async (e) => {
    result.sendClickError = String(e)
    await page.keyboard.press('Enter')
    result.usedEnterFallback = true
  })
  await sleep(1500)
  page.off('request', onReq)

  result.afterSend = await dumpComposer(page, 'after-send')
  result.playwrightRequests = requests.filter((r) =>
    /trae|chat|message|session|conversation|agent|sse|stream|ws/i.test(r.url) ||
    r.type === 'websocket' ||
    r.type === 'fetch' ||
    r.type === 'xhr',
  )
  result.observers = await readObservers(page)

  result.conversationSample = await page.evaluate(() => {
    const turns = [...document.querySelectorAll('.turn, .user-message, [data-role="user"]')]
    return {
      turnCount: turns.length,
      lastTexts: turns.slice(-4).map((el) => (el.innerText || '').slice(0, 200)),
      userMessages: [...document.querySelectorAll('[data-role="user"], .user-message__text-content, .user-message-query-text')]
        .map((el) => (el.innerText || '').slice(0, 160))
        .slice(-6),
    }
  })

  return result
}

async function probeAskora(page) {
  const result = { site: 'askora', steps: {} }
  result.initialUrl = page.url()
  await installObservers(page)

  const clicked = await clickNewConversation(page)
  result.clickNew = clicked
  await sleep(400)
  result.afterNew = await dumpComposer(page, 'after-new')

  const clickInput = await page.evaluate(() => {
    const el = document.querySelector('.chat-input-v2-input-box-editable, [contenteditable="true"]')
    if (!el) return { ok: false, reason: 'no-editable' }
    const r = el.getBoundingClientRect()
    const top = document.elementFromPoint(r.left + 20, r.top + 10)
    el.click()
    el.focus()
    return {
      ok: true,
      rect: { x: r.x, y: r.y, w: r.width, h: r.height },
      topAtPoint: top && { tag: top.tagName, className: String(top.className || '').slice(0, 160) },
      active: document.activeElement === el,
    }
  })
  result.clickInput = clickInput
  result.afterFocus = await dumpComposer(page, 'after-focus')

  await page.keyboard.type('Hello Askora', { delay: 20 })
  await sleep(200)
  result.afterType = await dumpComposer(page, 'after-type')

  await page.keyboard.press('Enter')
  await sleep(400)
  result.afterEnter = await dumpComposer(page, 'after-enter')

  const sendClick = await page.evaluate(() => {
    const btn = document.querySelector('.chat-input-v2-send-button')
    if (!btn) return { ok: false }
    const info = { className: btn.className, disabled: btn.disabled }
    btn.click()
    return { ok: true, ...info }
  })
  result.sendClick = sendClick
  await sleep(400)
  result.afterSend = await dumpComposer(page, 'after-send')
  result.observers = await readObservers(page)
  result.conversationSample = await page.evaluate(() => {
    const users = [...document.querySelectorAll('[data-role="user"], .user-message-query-text')]
    return {
      userCount: users.length,
      last: users.slice(-3).map((el) => (el.innerText || '').slice(0, 160)),
      viewHint: document.querySelector('.welcomeTitleWrapper-WfrDR6') ? 'new-task' : document.querySelector('#agent-chat-view') ? 'chat' : 'other',
    }
  })
  return result
}

async function main() {
  const browser = await chromium.connectOverCDP(WS)
  const pages = browser.contexts().flatMap((c) => c.pages())
  console.log('pages:', pages.map((p) => p.url()))

  let result
  if (TARGET === 'traework') {
    const page = pages.find((p) => p.url().includes('work.trae.ai'))
    if (!page) throw new Error('TraeWork tab not found')
    await page.bringToFront()
    result = await probeTraeWork(page)
  } else {
    const page = pages.find((p) => p.url().includes('127.0.0.1:5173') || p.url().includes('localhost:5173'))
    if (!page) throw new Error('Askora tab not found')
    await page.bringToFront()
    result = await probeAskora(page)
  }

  fs.writeFileSync(OUT.replace('.json', `.${TARGET}.json`), JSON.stringify(result, null, 2))
  console.log(JSON.stringify({
    site: result.site,
    clickNew: result.clickNew,
    afterNewClass: result.afterNew?.container,
    afterFocusClass: result.afterFocus?.container,
    afterTypeText: result.afterType?.editable?.text,
    afterTypeSend: result.afterType?.send,
    afterSendText: result.afterSend?.editable?.text,
    afterSendUsers: result.conversationSample,
  }, null, 2))
  await browser.close()
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
