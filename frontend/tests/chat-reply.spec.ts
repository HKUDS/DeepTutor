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

test.describe('chat reply from Lumen API', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('trae:sidebarOpen', '1')
      localStorage.setItem('trae:statusOpen', '0')
      localStorage.setItem('trae:theme', 'dark')
      if (!sessionStorage.getItem('deeptutor:test-ready')) {
        localStorage.removeItem('deeptutor:sessions')
        localStorage.removeItem('deeptutor:selectedSession')
        localStorage.removeItem('askora:sessions')
        localStorage.removeItem('askora:selectedSession')
        sessionStorage.setItem('deeptutor:test-ready', '1')
        sessionStorage.setItem('trae:view', 'chat')
      }
    })
  })

  test('hi 不讲授 general、不出现开门见山', async ({ page }) => {
    await mockDialogApi(page, { reply: '你好。当前还没有绑定学习活动，你想从哪份资料或哪个目标开始？' })
    const editable = await openNewConversation(page)
    await editable.pressSequentially('hi')
    await page.locator('.chat-input-v2-send-button').click()

    await expect(page.locator('.user-message-query-text').filter({ hasText: 'hi' })).toHaveCount(1)
    const assistant = page.locator('.markdown-renderer').last()
    await expect(assistant).toContainText('还没有绑定学习活动')
    await expect(assistant).not.toContainText('开门见山')
    await expect(assistant).not.toContainText('「general」')
    await expect(assistant).not.toContainText('这个词')
  })

  test('助手回复来自 Lumen WS，不是本地 echo', async ({ page }) => {
    await mockDialogApi(page)
    const editable = await openNewConversation(page)
    await editable.pressSequentially('Hello Askora')
    await page.locator('.chat-input-v2-send-button').click()

    await expect(page.locator('.user-message-query-text').filter({ hasText: 'Hello Askora' })).toHaveCount(1)
    await expect(page.locator('.markdown-renderer').last()).toContainText(MOCK_REPLY)
    await expect(page.locator('.markdown-renderer')).not.toContainText('本地 mock 回复')
    await expect(page.locator('.taskItem').first()).toHaveClass(/taskItemSelected/)
  })

  test('创建会话失败时保留用户句并在助手位报错', async ({ page }) => {
    await mockDialogApi(page, { createStatus: 500 })
    const editable = await openNewConversation(page)
    await editable.pressSequentially('create will fail')
    await page.locator('.chat-input-v2-send-button').click()

    await expect(page.locator('.user-message-query-text').filter({ hasText: 'create will fail' })).toHaveCount(1)
    await expect(page.locator('.markdown-renderer').last()).toContainText('会话创建失败，请重试。')
    await expect(page.locator('.markdown-renderer')).not.toContainText('本地 mock 回复')
  })

  test('stream 失败时保留用户句并在助手位报错', async ({ page }) => {
    await mockDialogApi(page, { streamError: '教学编排失败，请重试' })
    const editable = await openNewConversation(page)
    await editable.pressSequentially('stream will fail')
    await page.locator('.chat-input-v2-send-button').click()

    await expect(page.locator('.user-message-query-text').filter({ hasText: 'stream will fail' })).toHaveCount(1)
    await expect(page.locator('.markdown-renderer').last()).toContainText('教学编排失败，请重试')
    await expect(page.locator('.markdown-renderer')).not.toContainText('本地 mock 回复')
  })

  test('发送后等待回复时不出现正在连接或正在回复', async ({ page }) => {
    await mockDialogApi(page, { reply: '布是很多细线编起来的。', delayMs: 900 })
    const editable = await openNewConversation(page)
    await editable.pressSequentially('纱线是什么')
    await page.locator('.chat-input-v2-send-button').click()

    const assistant = page.locator('[data-role="assistant"]').last()
    await expect(page.locator('.user-message-query-text').filter({ hasText: '纱线是什么' })).toHaveCount(1)
    await expect(assistant.locator('.agent-message__title')).toHaveText('Lumen')
    await expect(assistant.locator('.markdown-renderer')).toHaveCount(0)
    await expect(assistant.locator('.latest-assistant-bar')).toHaveCount(0)
    await expect(page.getByText('正在连接')).toHaveCount(0)
    await expect(page.getByText('正在回复')).toHaveCount(0)
    await expect(page.getByText('正在**')).toHaveCount(0)

    await expect(assistant.locator('.markdown-renderer')).toContainText('布是很多细线编起来的。')
    await expect(page.getByText('正在连接')).toHaveCount(0)
    await expect(page.getByText('正在回复')).toHaveCount(0)
  })

  test('助手回复不展示思考过程、阶段名和工具日志', async ({ page }) => {
    await mockDialogApi(page, {
      noisy: true,
      reply: '把一块布想成很多很细的线做出来的。',
    })
    const editable = await openNewConversation(page)
    await editable.pressSequentially('我不知道纱线是什么')
    await page.locator('.chat-input-v2-send-button').click()

    const assistant = page.locator('[data-role="assistant"]').last()
    await expect(assistant.locator('.markdown-renderer')).toContainText('把一块布想成很多很细的线做出来的。')
    await expect(page.locator('.core-expandable-section__header-title')).toHaveCount(0)
    await expect(assistant).not.toContainText('思考过程')
    await expect(assistant).not.toContainText('Planning Socratic')
    await expect(assistant).not.toContainText('responding')
    await expect(assistant).not.toContainText('探索')
    await expect(assistant).not.toContainText('mastery_status')
    await expect(assistant).not.toContainText('"status":"active"')
  })

  test('助手底栏四个图标：复制用官方 SVG，悬停出提示，赞踩互斥，复制后对勾', async ({ page }) => {
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await mockDialogApi(page, { reply: '收到。' })
    const editable = await openNewConversation(page)
    await editable.pressSequentially('回一句很短的确认即可')
    await page.locator('.chat-input-v2-send-button').click()

    const bar = page.locator('[data-role="assistant"]').last().locator('.latest-assistant-bar')
    await expect(bar).toBeVisible()
    const like = bar.locator('button[aria-label="赞"]')
    const unlike = bar.locator('button[aria-label="踩"]')
    const copy = bar.locator('button[aria-label="复制全部"]')
    const retry = bar.locator('button[aria-label="重试"]')
    await expect(like).toBeVisible()
    await expect(unlike).toBeVisible()
    await expect(copy).toBeVisible()
    await expect(retry).toBeVisible()
    await expect(copy.locator('.trae-icon-Copy')).toHaveCount(1)
    const copyHtml = await copy.innerHTML()
    expect(copyHtml).toContain('M10.0415 8.53288')
    expect(copyHtml).toContain('13.9585 5.86687V7.99968Z')

    await like.hover()
    await expect(page.locator('[role="tooltip"]')).toHaveText('赞')
    await unlike.hover()
    await expect(page.locator('[role="tooltip"]')).toHaveText('踩')
    await copy.hover()
    await expect(page.locator('[role="tooltip"]')).toHaveText('复制全部')
    await retry.hover()
    await expect(page.locator('[role="tooltip"]')).toHaveText('重试')

    await like.click()
    await expect(like).toHaveClass(/active/)
    await expect(like.locator('.trae-icon-Like_fill')).toHaveCount(1)
    await unlike.click()
    await expect(unlike).toHaveClass(/active/)
    await expect(unlike.locator('.trae-icon-Unlike_fill')).toHaveCount(1)
    await expect(like).not.toHaveClass(/active/)
    await expect(like.locator('.trae-icon-Like_fill')).toHaveCount(0)

    await copy.click()
    await expect(copy).toHaveClass(/checked/)
    await expect(copy.locator('.trae-icon-check')).toHaveCount(1)
    await expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('收到。')
  })

  test('已有会话发送会继续该会话', async ({ page }) => {
    await mockDialogApi(page)

    await page.goto('/')
    await page.waitForSelector('.app-root')
    await page.locator('.taskItem').filter({ hasText: 'Greeting' }).click()
    const box = page.locator('.messageInputChatInputConversation .chat-input-v2-input-box-editable')
    await expect(box).toBeVisible()
    await box.click()
    await box.pressSequentially('from greeting seed')
    await page.locator('.chat-input-v2-send-button').click()

    await expect(page.locator('.user-message-query-text').filter({ hasText: 'from greeting seed' })).toHaveCount(1)
    await expect(page.locator('.markdown-renderer').last()).toContainText(MOCK_REPLY)
    await expect(page.locator('.taskItem').filter({ hasText: 'Greeting' })).toHaveClass(/taskItemSelected/)
  })
})
