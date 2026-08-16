import { test, expect, Page } from '@playwright/test'
import { mockDialogApi } from './dialog-api'

const MARKDOWN_FIXTURE = [
  '## 标题',
  '',
  '段落一。',
  '',
  '这是 **粗体** 和 *斜体* 以及 ~~删除~~ 和 `行内`。',
  '',
  '> 引用句',
  '',
  '- 无序甲',
  '  - 嵌套乙',
  '',
  '1. 有序一',
  '',
  '- [ ] 待办',
  '- [x] 已办',
  '',
  '| 列A | 列B |',
  '| --- | --- |',
  '| 1 | **二** |',
  '',
  '[示例链接](https://example.com)',
  '',
  '![示意](https://example.com/x.png)',
  '',
  '---',
  '',
  '价格 $5 and $10。例子 $3^2+4^2=5^2$。',
  '',
  '行内公式 \\(E=mc^2\\) 与块公式：',
  '',
  '$$',
  'a^2+b^2=c^2',
  '$$',
  '',
  '```python',
  'print("**not bold**")',
  '# heading',
  '```',
  '',
  '[危险](javascript:alert(1))',
].join('\n')

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

test.describe('assistant markdown contract C1–C16', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('trae:sidebarOpen', '1')
      localStorage.setItem('trae:statusOpen', '0')
      localStorage.setItem('trae:theme', 'dark')
      if (!sessionStorage.getItem('deeptutor:test-ready')) {
        localStorage.removeItem('deeptutor:sessions')
        localStorage.removeItem('deeptutor:selectedSession')
        sessionStorage.setItem('deeptutor:test-ready', '1')
        sessionStorage.setItem('trae:view', 'chat')
      }
    })
  })

  test('助手气泡按合同渲染结构，复制仍是源文本', async ({ page }) => {
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await mockDialogApi(page, { reply: MARKDOWN_FIXTURE })
    const editable = await openNewConversation(page)
    await editable.pressSequentially('render markdown')
    await page.locator('.chat-input-v2-send-button').click()

    const root = page.locator('.markdown-renderer').last()
    await expect(root.locator('h2.markdown-h2')).toHaveText('标题')
    await expect(root.locator('p.markdown-p').first()).toHaveText('段落一。')
    await expect(root.locator('strong').first()).toHaveText('粗体')
    await expect(root.locator('em')).toContainText('斜体')
    await expect(root.locator('del')).toContainText('删除')
    await expect(root.locator('code.markdown-inline-code')).toHaveText('行内')
    await expect(root.locator('blockquote')).toContainText('引用句')
    await expect(root.locator('ul.markdown-ul').first()).toContainText('无序甲')
    await expect(root.locator('ol.markdown-ol')).toContainText('有序一')
    await expect(root.locator('input.markdown-task')).toHaveCount(2)
    await expect(root.locator('input.markdown-task').nth(1)).toBeChecked()
    await expect(root.locator('table.markdown-table')).toContainText('列A')
    await expect(root.locator('table.markdown-table strong')).toHaveText('二')
    const link = root.locator('a.markdown-a', { hasText: '示例链接' })
    await expect(link).toHaveAttribute('href', 'https://example.com')
    await expect(link).toHaveAttribute('target', '_blank')
    await expect(root.locator('img.markdown-img')).toHaveAttribute('src', 'https://example.com/x.png')
    await expect(root.locator('hr.markdown-hr')).toHaveCount(1)
    await expect(root).toContainText('$5 and $10')
    await expect(root.locator('.katex').filter({ hasText: '$5' })).toHaveCount(0)
    await expect(root.locator('.katex').filter({ hasText: '3' }).first()).toBeVisible()
    await expect(root.locator('.katex').filter({ hasText: 'E' }).first()).toBeVisible()
    await expect(root.locator('.katex-display')).toBeVisible()
    await expect(root.locator('pre.markdown-pre')).toContainText('print("**not bold**")')
    await expect(root.locator('pre.markdown-pre strong')).toHaveCount(0)
    await expect(root.locator('pre.markdown-pre')).toContainText('# heading')
    await expect(root.locator('a.markdown-a', { hasText: '危险' })).not.toHaveAttribute('href', /javascript:/)

    await expect(page.locator('.user-message-query-text')).toHaveText('render markdown')

    const copy = page.locator('[data-role="assistant"]').last().locator('button[aria-label="复制全部"]')
    await copy.click()
    await expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(MARKDOWN_FIXTURE)
  })

  test('用户气泡不渲染 Markdown', async ({ page }) => {
    await mockDialogApi(page, { reply: '好的。' })
    const editable = await openNewConversation(page)
    await editable.pressSequentially('请看 **不是粗体**')
    await page.locator('.chat-input-v2-send-button').click()
    await expect(page.locator('.user-message-query-text')).toHaveText('请看 **不是粗体**')
    await expect(page.locator('.user-message-query-text strong')).toHaveCount(0)
  })

  test('流式未闭合围栏不把整段塌回源码', async ({ page }) => {
    await mockDialogApi(page, {
      chunks: ['```python\nprint("hi"', '\n```\n结束。'],
      chunkDelayMs: 80,
    })
    const editable = await openNewConversation(page)
    await editable.pressSequentially('stream fence')
    await page.locator('.chat-input-v2-send-button').click()

    const root = page.locator('.markdown-renderer').last()
    await expect(root.locator('pre.markdown-pre')).toBeVisible()
    await expect(root).not.toContainText('```python')
    await expect(root).toContainText('结束。')
    await expect(root.locator('pre.markdown-pre code')).toContainText('print("hi"')
  })
})
