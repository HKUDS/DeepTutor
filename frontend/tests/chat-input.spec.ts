import { test, expect, Page } from '@playwright/test'
import { MOCK_REPLY, mockDialogApi } from './dialog-api'

async function openNewConversation(page: Page) {
  await page.goto('/')
  await page.waitForSelector('.app-root')
  await page.locator('.navItem-r4wswG').filter({ hasText: '新建对话' }).click()
  const box = page.locator('.messageInputChatInputHome .chat-input-v2-input-box-wrapper')
  await expect(box).toBeVisible()
  const editable = page.locator('.messageInputChatInputHome .chat-input-v2-input-box-editable')
  await box.click()
  await expect(editable).toBeFocused()
  return editable
}

async function composer(page: Page) {
  return page.locator('.chat-input-v2-input-box-editable').first()
}

async function sendButton(page: Page) {
  return page.locator('.chat-input-v2-send-button').first()
}

async function userBubbles(page: Page) {
  return page.locator('.user-message-query-text')
}

test.describe('chat input', () => {
  test.beforeEach(async ({ page }) => {
    await mockDialogApi(page)
    await page.addInitScript(() => {
      localStorage.setItem('trae:sidebarOpen', '1')
      localStorage.setItem('trae:statusOpen', '0')
      localStorage.setItem('trae:theme', 'dark')
      sessionStorage.setItem('trae:view', 'chat')
    })
  })

  test('Case 1: 新建对话 → 输入 Hello Askora → 点击发送', async ({ page }) => {
    const editable = await openNewConversation(page)
    await editable.pressSequentially('Hello Askora')
    const send = await sendButton(page)
    await expect(send).toBeEnabled()
    await send.click()
    await expect(page.locator('#agent-chat-view')).toBeVisible()
    await expect((await userBubbles(page)).filter({ hasText: 'Hello Askora' })).toHaveCount(1)
    await expect(page.locator('.chat-input-v2-container').first()).toHaveClass(/--empty/)
    await expect(await composer(page)).toBeFocused()
  })

  test('Case 2: IME 输入中文时 Enter 不提前发送', async ({ page }) => {
    const editable = await openNewConversation(page)
    await editable.click()
    await editable.evaluate((el) => {
      el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true, data: '' }))
      const p = el.querySelector('p') ?? el
      p.textContent = '测试'
      el.dispatchEvent(new CompositionEvent('compositionupdate', { bubbles: true, data: '测试' }))
      el.dispatchEvent(new InputEvent('input', {
        bubbles: true,
        data: '测试',
        inputType: 'insertCompositionText',
        isComposing: true,
      }))
    })
    await page.keyboard.press('Enter')
    await expect(await userBubbles(page)).toHaveCount(0)
    await expect(page.locator('.welcomeTitleWrapper-WfrDR6')).toBeVisible()
    await editable.evaluate((el) => {
      const p = el.querySelector('p') ?? el
      p.textContent = '测试中文输入'
      el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '测试中文输入' }))
      el.dispatchEvent(new InputEvent('input', {
        bubbles: true,
        data: '测试中文输入',
        inputType: 'insertCompositionText',
        isComposing: false,
      }))
    })
    await expect(await userBubbles(page)).toHaveCount(0)
    await expect(editable).toContainText('测试中文输入')
  })

  test('Case 3: Shift+Enter 换行不发送', async ({ page }) => {
    const editable = await openNewConversation(page)
    await editable.pressSequentially('first line')
    await page.keyboard.press('Shift+Enter')
    await expect(await userBubbles(page)).toHaveCount(0)
    await expect(page.locator('.welcomeTitleWrapper-WfrDR6')).toBeVisible()
    const text = await editable.innerText()
    expect(text).toContain('first line')
    expect(text.includes('\n') || (await editable.locator('br').count()) > 0).toBeTruthy()
  })

  test('Case 4: Enter 发送', async ({ page }) => {
    const editable = await openNewConversation(page)
    await editable.pressSequentially('Send by Enter')
    await page.keyboard.press('Enter')
    await expect((await userBubbles(page)).filter({ hasText: 'Send by Enter' })).toHaveCount(1)
    await expect(page.locator('#agent-chat-view')).toBeVisible()
    await expect(page.locator('.chat-input-v2-container').first()).toHaveClass(/--empty/)
  })

  test('Case 5: 空输入是 voice-call 外观且不发送', async ({ page }) => {
    await openNewConversation(page)
    const send = await sendButton(page)
    await expect(send).toHaveClass(/voice-call-mode/)
    await expect(send).not.toHaveClass(/disabled/)
    await expect(send).toBeEnabled()
    await send.click()
    await page.keyboard.press('Enter')
    await expect(await userBubbles(page)).toHaveCount(0)
    await expect(page.locator('.welcomeTitleWrapper-WfrDR6')).toBeVisible()
  })

  test('Case 6: 连续发送 3 条消息', async ({ page }) => {
    const first = await openNewConversation(page)
    await first.pressSequentially('message one')
    await (await sendButton(page)).click()
    await expect((await userBubbles(page)).filter({ hasText: 'message one' })).toHaveCount(1)
    await expect(page.locator('.markdown-renderer').last()).toContainText(MOCK_REPLY)

    const box = await composer(page)
    await expect(box).toBeFocused()
    await box.pressSequentially('message two')
    await page.keyboard.press('Enter')
    await expect((await userBubbles(page)).filter({ hasText: 'message two' })).toHaveCount(1)

    await expect(box).toBeFocused()
    await box.pressSequentially('message three')
    await (await sendButton(page)).click()
    await expect((await userBubbles(page)).filter({ hasText: 'message three' })).toHaveCount(1)

    await expect(await userBubbles(page)).toHaveCount(3)
    await expect(page.locator('.chat-input-v2-container').first()).toHaveClass(/--empty/)
    await expect(box).toBeFocused()
    await expect(await sendButton(page)).toHaveClass(/voice-call-mode/)
    await expect(await sendButton(page)).not.toHaveClass(/disabled/)
  })

  test('Welcome 输入框几何对齐 TraeWork home', async ({ page }) => {
    await openNewConversation(page)
    const editor = page.locator('.messageInputChatInputHome .chat-input-v2-editor-part')
    const wrapper = page.locator('.messageInputChatInputHome .chat-input-v2-input-box-wrapper')
    const plus = page.locator('.messageInputChatInputHome .messageInputToolbarIconBtn')
    const send = page.locator('.messageInputChatInputHome .chat-input-v2-send-button')
    await expect(editor).toHaveCSS('min-height', 'auto')
    await expect(wrapper).toHaveCSS('min-height', '62px')
    await expect(wrapper).toHaveCSS('max-height', '142px')
    await expect(wrapper).toHaveCSS('display', 'block')
    const editorBox = await editor.boundingBox()
    const plusBox = await plus.boundingBox()
    const sendBox = await send.boundingBox()
    expect(editorBox?.height).toBe(128)
    expect(plusBox?.width).toBe(32)
    expect(plusBox?.height).toBe(32)
    expect(sendBox?.width).toBe(32)
    expect(sendBox?.height).toBe(32)
    await expect(send).toHaveClass(/voice-call-mode/)
    await expect(page.locator('.messageInputChatInputHome .core-model-select-trigger')).toHaveCSS('height', '32px')
    await expect(page.locator('.messageInputChatInputHome .core-model-select-trigger')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)')
  })

  test('已有对话输入框几何对齐 TraeWork session', async ({ page }) => {
    const editable = await openNewConversation(page)
    await editable.pressSequentially('open existing conversation')
    await (await sendButton(page)).click()
    await expect(page.locator('#agent-chat-view')).toBeVisible()
    const editor = page.locator('.messageInputChatInputConversation .chat-input-v2-editor-part')
    const wrapper = page.locator('.messageInputChatInputConversation .chat-input-v2-input-box-wrapper')
    const send = page.locator('.messageInputChatInputConversation .chat-input-v2-send-button')
    await expect(wrapper).toHaveCSS('min-height', '68px')
    const editorBox = await editor.boundingBox()
    const sendBox = await send.boundingBox()
    expect(editorBox?.height).toBe(134)
    expect(sendBox?.width).toBe(32)
    expect(sendBox?.height).toBe(32)
    await expect(send).toHaveClass(/voice-call-mode/)
    await expect(page.locator('.chat-input-v2-container').first()).toHaveClass(/messageInputChatInputConversation/)
  })
})
