#!/usr/bin/env node
import { chromium } from 'playwright'
import fs from 'node:fs'

const CDP = process.env.CDP_URL || 'http://[::1]:9222'
const OUT = new URL('./probe-sidebar-session.result.json', import.meta.url)
const MARK = `AskoraSidebarProbe ${Date.now()}`

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

async function snapshotSidebar(page, label) {
  return page.evaluate((labelInner) => {
    const nav = [...document.querySelectorAll('.navItem-r4wswG')].map((el) => ({
      text: (el.innerText || '').replace(/\s+/g, ' ').trim(),
      className: String(el.className || ''),
      active: el.className.includes('navItemActive'),
    }))
    const items = [...document.querySelectorAll('.taskItem, [data-session-id]')].map((el) => {
      const row = el.classList?.contains('taskItem') ? el : el.querySelector('.taskItem') || el
      return {
        sessionId: el.getAttribute('data-session-id') || row.getAttribute('data-session-id') || '',
        text: (row.innerText || el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 160),
        selected: String(row.className || '').includes('taskItemSelected') || String(el.className || '').includes('Selected'),
        className: String(row.className || el.className || '').slice(0, 200),
      }
    })
    const unique = []
    const seen = new Set()
    for (const it of items) {
      const key = it.sessionId || it.text
      if (seen.has(key)) continue
      seen.add(key)
      unique.push(it)
    }
    return {
      label: labelInner,
      url: location.href,
      title: document.title,
      heading: (document.querySelector('.projectsHeading-UVr4Aj, .projectsHeading')?.innerText || '').trim(),
      nav,
      items: unique,
      selectedHeader: (document.querySelector('.taskName-iaeIsX')?.innerText || '').trim(),
      headerTime: (document.querySelector('.timeText-bjF8AM')?.innerText || '').trim(),
      isHome: !!document.querySelector('.messageInputChatInputHome, .homeMessageInput-bhe4cx, .welcomeTitleWrapper-WfrDR6'),
      isConversation: !!document.querySelector('.messageInputChatInputConversation, #agent-chat-view'),
    }
  }, label)
}

async function main() {
  const browser = await chromium.connectOverCDP(CDP)
  const page = browser.contexts().flatMap((c) => c.pages()).find((p) => p.url().includes('work.trae.ai'))
  if (!page) throw new Error('TraeWork tab not found in debug Chrome')
  await page.bringToFront()
  await page.waitForTimeout(500)

  const result = { mark: MARK, steps: {} }
  result.before = await snapshotSidebar(page, 'before')

  const clicked = await page.evaluate(() => {
    const hit = [...document.querySelectorAll('.navItem-r4wswG, [role="button"], button')].find((el) => {
      const t = (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, '')
      return t.includes('新建任务') || t.includes('新建对话')
    })
    if (!hit) return { ok: false }
    hit.click()
    return { ok: true, text: (hit.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80) }
  })
  result.clickNew = clicked
  await sleep(800)
  result.afterNewClick = await snapshotSidebar(page, 'after-new-click')

  const requests = []
  const onReq = (req) => {
    const url = req.url()
    if (/chat_session|session|conversation|task/i.test(url)) {
      requests.push({ t: Date.now(), method: req.method(), type: req.resourceType(), url: url.slice(0, 280) })
    }
  }
  const responses = []
  const onRes = async (res) => {
    const url = res.url()
    if (!/chat_session/i.test(url)) return
    let body = null
    try {
      const ct = res.headers()['content-type'] || ''
      if (ct.includes('json')) body = await res.json()
    } catch { /* ignore */ }
    responses.push({
      t: Date.now(),
      status: res.status(),
      method: res.request().method(),
      url: url.slice(0, 280),
      bodyPreview: body && JSON.stringify(body).slice(0, 1200),
    })
  }
  page.on('request', onReq)
  page.on('response', onRes)

  const editable = page.locator('.chat-input-v2-input-box-editable').first()
  await editable.click({ timeout: 8000 })
  await page.keyboard.press('Meta+A')
  await page.keyboard.press('Backspace')
  await editable.pressSequentially(MARK, { delay: 15 })
  await sleep(300)
  result.afterType = await snapshotSidebar(page, 'after-type')

  const send = page.locator('.chat-input-v2-send-button').first()
  await send.click({ timeout: 5000 })
  await sleep(1500)
  result.afterSend1_5s = await snapshotSidebar(page, 'after-send-1.5s')
  await sleep(2500)
  result.afterSend4s = await snapshotSidebar(page, 'after-send-4s')

  page.off('request', onReq)
  page.off('response', onRes)
  result.requests = requests
  result.responses = responses

  result.delta = {
    itemsBeforeNew: result.before.items.map((i) => i.text),
    itemsAfterNewClick: result.afterNewClick.items.map((i) => i.text),
    itemsAfterSend: result.afterSend4s.items.map((i) => i.text),
    newAfterClick: result.afterNewClick.items.filter((a) => !result.before.items.some((b) => (b.sessionId && b.sessionId === a.sessionId) || b.text === a.text)),
    newAfterSend: result.afterSend4s.items.filter((a) => !result.afterNewClick.items.some((b) => (b.sessionId && b.sessionId === a.sessionId) || b.text === a.text)),
    urlBefore: result.before.url,
    urlAfterClick: result.afterNewClick.url,
    urlAfterSend: result.afterSend4s.url,
    headerAfterSend: result.afterSend4s.selectedHeader,
    selectedAfterSend: result.afterSend4s.items.filter((i) => i.selected),
  }

  fs.writeFileSync(OUT, JSON.stringify(result, null, 2))
  console.log(JSON.stringify({
    mark: MARK,
    clickNew: clicked,
    url: { before: result.before.url, afterClick: result.afterNewClick.url, afterSend: result.afterSend4s.url },
    counts: {
      before: result.before.items.length,
      afterClick: result.afterNewClick.items.length,
      afterSend: result.afterSend4s.items.length,
    },
    newAfterClick: result.delta.newAfterClick,
    newAfterSend: result.delta.newAfterSend,
    headerAfterSend: result.afterSend4s.selectedHeader,
    selectedAfterSend: result.delta.selectedAfterSend,
    createRequests: requests.filter((r) => r.method === 'POST'),
    createResponses: responses.filter((r) => r.method === 'POST' || /chat_sessions$/.test(r.url)),
  }, null, 2))
  await browser.close()
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
