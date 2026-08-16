import { test, expect, Page } from '@playwright/test'
import { mockDialogApi } from './dialog-api'

async function openNewConversation(page: Page) {
  await page.locator('.navItem-r4wswG').filter({ hasText: '新建对话' }).click()
  const box = page.locator('.messageInputChatInputHome .chat-input-v2-input-box-wrapper')
  await expect(box).toBeVisible()
  return box
}

function sidebarLabels(page: Page) {
  return page.locator('.taskItem .taskText')
}

test.describe('sidebar sessions', () => {
  test.beforeEach(async ({ page }) => {
    await mockDialogApi(page)
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
    await page.goto('/')
    await page.waitForSelector('.app-root')
  })

  test('点击新建对话不新增侧栏条目', async ({ page }) => {
    const before = await sidebarLabels(page).allTextContents()
    await openNewConversation(page)
    await expect(page.locator('.navItem-r4wswG').filter({ hasText: '新建对话' })).toHaveClass(/navItemActive/)
    await expect(sidebarLabels(page)).toHaveText(before)
    await expect(page.locator('.taskItem.taskItemSelected')).toHaveCount(0)
  })

  test('第一条消息发出后插入侧栏顶部并改写标题', async ({ page }) => {
    const beforeCount = await sidebarLabels(page).count()
    const box = await openNewConversation(page)
    const editable = page.locator('.messageInputChatInputHome .chat-input-v2-input-box-editable')
    await box.click()
    await editable.pressSequentially('AskoraSidebarProbe 1786809999999')
    await page.locator('.chat-input-v2-send-button').click()

    await expect(page.locator('#agent-chat-view')).toBeVisible()
    await expect(page.locator('.user-message-query-text').filter({ hasText: 'AskoraSidebarProbe' })).toHaveCount(1)
    await expect(sidebarLabels(page)).toHaveCount(beforeCount + 1)

    const first = sidebarLabels(page).first()
    await expect(first).toHaveText('新对话')
    await expect(page.locator('.taskName-iaeIsX')).toHaveText('新对话')
    await expect(page.locator('.taskItem').first()).toHaveClass(/taskItemSelected/)
    await expect(page.locator('.navItem-r4wswG').filter({ hasText: '新建对话' })).not.toHaveClass(/navItemActive/)

    await expect(first).toHaveText('Askora Sidebar Probe', { timeout: 2000 })
    await expect(page.locator('.taskName-iaeIsX')).toHaveText('Askora Sidebar Probe')
  })

  test('点侧栏切换会话且不串台', async ({ page }) => {
    const box = await openNewConversation(page)
    await box.click()
    await page.locator('.messageInputChatInputHome .chat-input-v2-input-box-editable').pressSequentially('alpha session')
    await page.locator('.chat-input-v2-send-button').click()
    await expect(page.locator('.user-message-query-text').filter({ hasText: 'alpha session' })).toHaveCount(1)

    await page.locator('.taskItem').filter({ hasText: 'Greeting' }).click()
    await expect(page.locator('.taskName-iaeIsX')).toHaveText('Greeting')
    await expect(page.locator('.user-message-query-text').filter({ hasText: 'hi' })).toHaveCount(1)
    await expect(page.locator('.user-message-query-text').filter({ hasText: 'alpha session' })).toHaveCount(0)

    await page.locator('.taskItem').filter({ hasText: 'alpha session' }).click()
    await expect(page.locator('.user-message-query-text').filter({ hasText: 'alpha session' })).toHaveCount(1)
    await expect(page.locator('.taskName-iaeIsX')).toHaveText('alpha session')
  })

  test('置顶 / 重命名 / 删除真正改侧栏', async ({ page }) => {
    const box = await openNewConversation(page)
    await box.click()
    await page.locator('.messageInputChatInputHome .chat-input-v2-input-box-editable').pressSequentially('beta session')
    await page.locator('.chat-input-v2-send-button').click()
    await expect(page.locator('.taskItem .taskText').first()).toHaveText('beta session')

    const beta = page.locator('.taskItem').filter({ hasText: 'beta session' })
    await beta.hover()
    await beta.getByRole('button', { name: '更多' }).click()
    await page.locator('.taskMenu').getByRole('menuitem', { name: '重命名' }).click()
    const pop = page.locator('.renamePopover-bnrET0')
    await expect(pop).toBeVisible()
    const input = pop.locator('.renameInput-q2DQZg')
    await expect(input).toBeFocused()
    await input.fill('beta renamed')
    await pop.getByRole('button', { name: '确认' }).click()
    await expect(pop).toHaveCount(0)
    await expect(page.locator('.taskItem .taskText').filter({ hasText: 'beta renamed' })).toHaveCount(1)
    await expect(page.locator('.taskName-iaeIsX')).toHaveText('beta renamed')

    const greeting = page.locator('.projectsListContent-n9sJMQ .taskItem').filter({ hasText: 'Greeting' })
    await greeting.hover()
    await greeting.getByRole('button', { name: '置顶' }).click()
    const pinned = page.locator('.pinnedSectionList .taskItem')
    await expect(page.locator('.pinnedSectionHeadingText')).toHaveText('置顶')
    await expect(pinned).toHaveCount(1)
    await expect(pinned.first()).toHaveClass(/pinnedTaskItem/)
    await expect(pinned.first().locator('.taskText')).toHaveText('Greeting')
    await expect(pinned.first().locator('.pinIconAlways')).toBeVisible()
    await expect(page.locator('.projectsListContent-n9sJMQ .taskItem').filter({ hasText: 'Greeting' })).toHaveCount(0)
    await pinned.first().hover()
    await pinned.first().getByRole('button', { name: '更多' }).click()
    await expect(page.locator('.taskMenu').getByRole('menuitem', { name: '取消置顶' })).toBeVisible()
    await page.keyboard.press('Escape')

    const renamed = page.locator('.taskItem').filter({ hasText: 'beta renamed' })
    await renamed.hover()
    await renamed.getByRole('button', { name: '更多' }).click()
    await page.locator('.taskMenu').getByRole('menuitem', { name: '删除任务' }).click()
    await expect(page.locator('.taskItem .taskText').filter({ hasText: 'beta renamed' })).toHaveCount(0)
    await expect(page.locator('.taskItem .taskText').filter({ hasText: 'Greeting' })).toHaveCount(1)
  })

  test('刷新后会话仍在侧栏', async ({ page }) => {
    const box = await openNewConversation(page)
    await box.click()
    await page.locator('.messageInputChatInputHome .chat-input-v2-input-box-editable').pressSequentially('persist me')
    await page.locator('.chat-input-v2-send-button').click()
    await expect(page.locator('.taskItem .taskText').first()).toHaveText('persist me')

    await page.reload()
    await page.waitForSelector('.app-root')
    await expect(page.locator('.taskItem .taskText').first()).toHaveText('persist me')
    await expect(page.locator('.user-message-query-text').filter({ hasText: 'persist me' })).toHaveCount(1)
  })
})
