import { randomUUID } from 'node:crypto'

import { expect, test as base, type Page } from '@playwright/test'
import JSZip from 'jszip'

async function illustratedEpub(options: {
  longPage?: boolean
  identifier: string
}): Promise<Buffer> {
  const zip = new JSZip()
  zip.file('mimetype', 'application/epub+zip', { compression: 'STORE' })
  zip.file(
    'META-INF/container.xml',
    "<?xml version='1.0'?><container xmlns='urn:oasis:names:tc:opendocument:xmlns:container'><rootfiles><rootfile full-path='OPS/book.opf' media-type='application/oebps-package+xml'/></rootfiles></container>"
  )
  zip.file(
    'OPS/book.opf',
    `<?xml version='1.0'?><package xmlns='http://www.idpf.org/2007/opf' xmlns:dc='http://purl.org/dc/elements/1.1/' version='3.0' unique-identifier='book-id'><metadata><dc:identifier id='book-id'>urn:uuid:${options?.identifier}</dc:identifier><dc:title>Faithful reader</dc:title><dc:language>en</dc:language></metadata><manifest><item id='nav' href='nav.xhtml' media-type='application/xhtml+xml' properties='nav'/><item id='one' href='one.xhtml' media-type='application/xhtml+xml'/><item id='two' href='two.xhtml' media-type='application/xhtml+xml'/><item id='dot' href='dot.png' media-type='image/png'/></manifest><spine><itemref idref='one'/><itemref idref='two'/></spine></package>`
  )
  zip.file(
    'OPS/nav.xhtml',
    "<html xmlns='http://www.w3.org/1999/xhtml' xmlns:epub='http://www.idpf.org/2007/ops'><body><nav epub:type='toc'><ol><li><a href='one.xhtml'>Illustrated chapter</a><ol><li><a href='one.xhtml#late-detail'>Late detail</a></li></ol></li><li><a href='two.xhtml'>Second chapter</a></li></ol></nav></body></html>"
  )
  zip.file(
    'OPS/one.xhtml',
    `<html xmlns='http://www.w3.org/1999/xhtml'><head><title>Illustrated chapter</title></head><body><h1 id='publisher-title'>Illustrated chapter</h1><h2>Source layout</h2>${options?.longPage ? "<div style='height: 2500px'></div>" : ''}<h3 id='late-detail'>Late detail</h3><p>This layout comes from the EPUB.</p><img alt='source illustration' src='dot.png'/></body></html>`
  )
  zip.file(
    'OPS/two.xhtml',
    "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>Second chapter</title></head><body><h1>Second chapter</h1><p>Keyboard navigation reached the second spine item.</p></body></html>"
  )
  zip.file(
    'OPS/dot.png',
    Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
      'base64'
    )
  )
  return zip.generateAsync({
    type: 'nodebuffer',
    mimeType: 'application/epub+zip',
  })
}

const test = base.extend<{
  openEpub: (options?: { longPage?: boolean }) => Promise<string>
}>({
  openEpub: async ({ page }, provide) => {
    const workspaces: string[] = []
    const materials: string[] = []
    try {
      await provide(async options => {
        const identifier = randomUUID()
        // Use the real upload, extraction, collection and session APIs. The
        // reader no longer lives in /chat?capability=immersive_reading.
        const uploaded = await page.request.post('/api/reading/materials', {
          multipart: {
            file: {
              name: `epub-reader-${identifier}.epub`,
              mimeType: 'application/epub+zip',
              buffer: await illustratedEpub({ ...options, identifier }),
            },
          },
        })
        expect(uploaded.ok(), await uploaded.text()).toBe(true)
        const material = await uploaded.json()
        materials.push(material.material_id)
        expect(material.render_mode).toBe('epub')

        const created = await page.request.post('/api/reading/workspaces', {
          data: { title: `EPUB audit ${identifier}`, material_ids: [material.material_id] },
        })
        expect(created.ok(), await created.text()).toBe(true)
        const { workspace } = await created.json()
        workspaces.push(workspace.workspace_id)
        const conversation = await page.request.post(
          `/api/reading/workspaces/${workspace.workspace_id}/sessions`,
          { data: { title: 'EPUB audit', active_material_id: material.material_id } }
        )
        expect(conversation.ok(), await conversation.text()).toBe(true)
        const { session } = await conversation.json()
        await page.goto(
          `/learning/reading/${workspace.workspace_id}/sessions/${session.session_id}`
        )
        return material.material_id
      })
    } finally {
      // Stop position updates before removing only this test's unique data.
      await page.goto('about:blank')
      for (const id of workspaces) {
        const removed = await page.request.delete(`/api/reading/workspaces/${id}`)
        expect(removed.ok(), await removed.text()).toBe(true)
      }
      for (const id of materials) {
        const removed = await page.request.delete(`/api/reading/materials/${id}`)
        expect(removed.ok(), await removed.text()).toBe(true)
      }
    }
  },
})

async function contents(page: Page) {
  const navigator = page.locator('.dt-reading-navigator')
  if (await navigator.isHidden()) {
    await page.getByRole('button', { name: 'Expand contents', exact: true }).click()
  }
  await expect(navigator).toBeVisible()
  return navigator
}

test('EPUB outline entries navigate to source anchors and chapters', async ({ page, openEpub }) => {
  const materialId = await openEpub({ longPage: true })

  const readerFrame = page.locator('iframe').contentFrame()
  await expect(readerFrame.getByRole('heading', { name: 'Illustrated chapter' })).toBeVisible()
  const lateDetail = readerFrame.getByRole('heading', { name: 'Late detail' })
  await expect(lateDetail).not.toBeInViewport()
  const positionUrl = `/api/reading/materials/${materialId}/position`
  await expect
    .poll(async () => (await (await page.request.get(positionUrl)).json()).source_anchor)
    .toMatch(/^epubcfi\(/)
  const firstAnchor = (await (await page.request.get(positionUrl)).json()).source_anchor
  await (await contents(page)).getByRole('button', { name: 'Late detail', exact: true }).click()
  await expect(lateDetail).toBeInViewport()

  await expect
    .poll(async () => {
      const position = await (await page.request.get(positionUrl)).json()
      return (
        position.locator === 1 &&
        /^epubcfi\(/.test(position.source_anchor) &&
        position.source_anchor !== firstAnchor
      )
    })
    .toBe(true)
  await page.reload()
  // Restoring only the chapter locator would return to its first page.
  await expect(lateDetail).toBeInViewport()

  await (await contents(page)).getByRole('button', { name: 'Second chapter', exact: true }).click()
  await expect(readerFrame.getByRole('heading', { name: 'Second chapter' })).toBeVisible()
  await expect(readerFrame.getByRole('heading', { name: 'Late detail' })).toHaveCount(0)
})

test('faithfully renders EPUB resources, navigates, and restores its CFI', async ({
  page,
  openEpub,
}, testInfo) => {
  const materialId = await openEpub()
  const readerFrame = page.locator('iframe').contentFrame()
  await expect(readerFrame.getByRole('heading', { name: 'Illustrated chapter' })).toBeVisible()
  await expect(readerFrame.getByAltText('source illustration')).toBeVisible()

  const turnForward =
    testInfo.project.name === 'epub-reader-webkit'
      ? () => page.getByRole('button', { name: 'Next', exact: true }).click()
      : async () => {
          await readerFrame.locator('body').click()
          await page.keyboard.press('ArrowRight')
        }
  for (let attempt = 0; attempt < 4; attempt += 1) {
    await turnForward()
    if (await readerFrame.getByRole('heading', { name: 'Second chapter' }).isVisible()) break
    await page.waitForTimeout(150)
  }
  await expect(readerFrame.getByRole('heading', { name: 'Second chapter' })).toBeVisible()
  await expect
    .poll(async () => {
      const position = await page.request.get(`/api/reading/materials/${materialId}/position`)
      return position.json()
    })
    .toMatchObject({ locator: 2, source_anchor: expect.stringMatching(/^epubcfi\(/) })

  await page.reload()
  const restoredFrame = page.locator('iframe').contentFrame()
  await expect(restoredFrame.getByRole('heading', { name: 'Second chapter' })).toBeVisible()
})
