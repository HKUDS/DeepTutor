import { expect, test } from '@playwright/test'
import { manualTopic, manualReport } from '../fixtures/mastery-manual'
import { sourceModuleInventory } from './fixtures/modules'
import { emptyLearningIndex } from './fixtures/learning-index'
import { emptyTaskBoard } from './fixtures/task-board'

for (const width of [1280, 390]) {
  test(`manual mastery and missing-question recovery at ${width}px`, async ({ page }, testInfo) => {
    const topic = structuredClone(manualTopic)
    const report = structuredClone(manualReport)
    const writes: string[] = []
    await page.setViewportSize({ width, height: 900 })
    await page.routeWebSocket('**/ws/**', socket => socket.close())
    // Every request and mutation stays in this disposable browser fixture.
    await page.route('**/api/**', async route => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      const json = (value: unknown) => route.fulfill({ json: value })
      if (path === '/api/modules') return json(sourceModuleInventory)
      if (path === '/api/auth/status')
        return json({ enabled: false, authenticated: true, role: 'admin', is_admin: true })
      if (path === '/api/settings/ui') return json({ language: 'en' })
      if (path === '/api/settings/llm-options')
        return json({
          active: { profile_id: 'fixture', model_id: 'fixture' },
          options: [
            {
              profile_id: 'fixture',
              model_id: 'fixture',
              profile_name: 'Fixture',
              model_name: 'Fixture',
              model: 'fixture',
              provider: 'openai',
              is_active_default: true,
            },
          ],
        })
      if (path === '/api/settings') return json({ ui: { language: 'en', theme: 'light' } })
      if (path === '/api/dashboard/learning-index') return json(emptyLearningIndex)
      if (path === '/api/task-board') return json(emptyTaskBoard)
      if (path.endsWith('/review-strategies')) return json({ strategies: [] })
      if (path.endsWith('/sessions')) return json({ sessions: [] })
      if (path === '/api/mastery-paths/topics/manual') return json(topic)
      if (path.endsWith('/objectives/kp1')) return json({ objective: report })
      if (path.endsWith('/events')) return json({ events: [], revision: topic.path_revision })
      if (path.endsWith('/kp1/defer') || path.endsWith('/kp1/override')) {
        expect(request.method()).toBe('POST')
        writes.push(path)
        const point = topic.map.modules[0].knowledge_points[0]
        if (path.endsWith('/defer')) {
          expect(request.postDataJSON()).toEqual({ note: 'The tutor did not show a question' })
          point.deferred = true
        } else {
          const mastered = request.postDataJSON().mastered
          point.deferred = false
          point.status = mastered ? 'mastered' : 'learning'
          point.mastery_source = mastered ? 'learner' : ''
          report.mastered = mastered
          report.mastery_source = point.mastery_source
          topic.map.counts.mastered = mastered ? 1 : 0
          topic.map.counts.learning = mastered ? 0 : 1
          topic.map.modules[0].mastered = mastered ? 1 : 0
        }
        topic.next.knowledge_point_id = 'kp2'
        topic.next.knowledge_point_name = 'Truth tables'
        topic.path_revision += 1
        return json({ status: 'ok', map: topic.map, path_revision: topic.path_revision })
      }
      return json({})
    })

    await page.goto('/learning/mastery/manual', { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: /Equivalent explanations/ }).click()
    await page.getByRole('button', { name: 'Skip this knowledge point for now' }).click()
    await expect(page.getByText(/Skipping does not count as mastery/)).toBeVisible()
    await page.getByLabel('Optional note').fill('The tutor did not show a question')
    await page.getByRole('button', { name: 'Skip for now', exact: true }).scrollIntoViewIfNeeded()
    await page.screenshot({
      path: testInfo.outputPath(`confirm-skip-${width}.png`),
      fullPage: true,
    })
    expect(writes).toHaveLength(0)
    await page.getByRole('button', { name: 'Skip for now', exact: true }).click()
    await expect(page.getByText('Deferred for now')).toBeAttached()
    expect(topic.map.counts.mastered).toBe(0)
    await expect(page.getByText(/Skipping does not count as mastery/)).toBeVisible()

    await page.getByRole('button', { name: 'I already know this — advance' }).click()
    await expect(page.getByText(/Confirming mastery counts toward progress/)).toBeVisible()
    await page.getByRole('button', { name: 'Confirm mastery', exact: true }).click()
    await expect(page.getByText('Confirmed by you')).toBeVisible()
    expect(topic.map.counts.mastered).toBe(1)
    await page.screenshot({ path: testInfo.outputPath(`confirmed-${width}.png`), fullPage: true })
    await page.getByRole('button', { name: 'Return to assessment' }).click()
    await expect(
      page.getByRole('button', { name: 'Skip this knowledge point for now' })
    ).toBeVisible()
    expect(topic.map.counts.mastered).toBe(0)
    expect(writes).toHaveLength(3)
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth
        )
      )
      .toBeLessThanOrEqual(1)
  })
}
