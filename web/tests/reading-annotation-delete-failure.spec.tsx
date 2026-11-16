import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadingProvider, useReading } from '@/context/ReadingContext'
import type { AnnotationItem, MaterialDetail } from '@/lib/reading-api'

const api = vi.hoisted(() => ({ fetch: vi.fn() }))
vi.mock('@/lib/api', () => ({ apiFetch: api.fetch, apiUrl: (url: string) => url }))

function mark(id: string): AnnotationItem {
  return {
    annotation_id: id,
    locator: 1,
    kind: 'highlight',
    color: 'yellow',
    quote: id,
    note: '',
    rects: [],
    source_anchor: '',
    author: 'user',
    created_at: 1,
    updated_at: 1,
  } as AnnotationItem
}

/** Storage events only reach *other* tabs, so the tests dispatch them directly. */
function broadcast(materialId: string) {
  window.dispatchEvent(
    new StorageEvent('storage', {
      key: 'dt.reader.annotationsRevision',
      newValue: JSON.stringify({ materialId, at: Date.now() }),
    })
  )
}

async function open(
  context: { current: ReturnType<typeof useReading> },
  id: string,
  marks: AnnotationItem[]
) {
  api.fetch.mockResolvedValueOnce(new Response(JSON.stringify(marks)))
  await act(async () => {
    await context.current.openMaterial({
      material_id: id,
      outline: [],
      revision: 1,
    } as unknown as MaterialDetail)
  })
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0))
const response = (rows: AnnotationItem[]) => new Response(JSON.stringify(rows))

beforeEach(() => {
  api.fetch.mockReset()
  localStorage.clear()
})
afterEach(() => {
  localStorage.clear()
})

/**
 * A failed DELETE has to roll the row back to what the server holds.
 *
 * The row this tab captured when the DELETE left can be older than the server:
 * another tab may have edited the mark while the request was in flight, and a
 * refresh may already have brought the newer copy here. Restoring the captured
 * object would put the old note back on screen over the newer one, and the
 * reader would see a stale mark until the next refresh or reopen.
 */
describe('a failed delete after a remote edit', () => {
  it("restores the server's note, not the copy captured before the DELETE", async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider })
    await open(result, 'doc-a', [{ ...mark('a'), note: 'old' }])

    // The DELETE is in flight and will fail.
    let rejectDelete!: (error: Error) => void
    api.fetch.mockImplementationOnce(
      () =>
        new Promise<Response>((_resolve, reject) => {
          rejectDelete = reject
        })
    )
    let removing!: Promise<boolean>
    act(() => {
      removing = result.current.removeMark(result.current.annotations[0])
    })

    // Another tab edits the same mark; the refresh lands the newer row here,
    // where the tombstone still hides it until the DELETE settles.
    api.fetch.mockResolvedValueOnce(response([{ ...mark('a'), note: 'edited remotely' }]))
    await act(async () => {
      broadcast('doc-a')
      await flush()
    })
    expect(result.current.annotations).toEqual([])

    // The DELETE fails, so this tab re-reads instead of trusting its capture.
    api.fetch.mockResolvedValueOnce(response([{ ...mark('a'), note: 'edited remotely' }]))
    await act(async () => {
      rejectDelete(new Error('offline'))
      await removing
      await flush()
    })

    expect(result.current.annotations).toHaveLength(1)
    expect(result.current.annotations[0].note).toBe('edited remotely')
    // The reader is still told the delete failed.
    expect(result.current.error).toBe('That annotation could not be removed.')
  })

  it('falls back to the captured row when the re-read fails too', async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider })
    await open(result, 'doc-a', [{ ...mark('a'), note: 'old' }])

    api.fetch.mockRejectedValueOnce(new Error('offline'))
    // The re-read that follows the failed DELETE fails as well.
    api.fetch.mockRejectedValueOnce(new Error('offline'))
    await act(async () => {
      const removed = await result.current.removeMark(result.current.annotations[0])
      expect(removed).toBe(false)
    })

    // A mark the server may still hold must not vanish because a GET failed.
    expect(result.current.annotations).toHaveLength(1)
    expect(result.current.annotations[0].note).toBe('old')
    expect(result.current.error).toBe('That annotation could not be removed.')
  })
})

/**
 * A mark still being created must not be deleted by its optimistic id.
 *
 * A brand-new mark lives under `pending-…` until its PUT returns. Deleting it
 * then sent that id to the server, which had never seen it: the DELETE 404'd
 * while the PUT created the real row, leaving a mark the server holds and this
 * tab has hidden — invisible until something else refreshed the list.
 */
describe('deleting a mark whose create is still in flight', () => {
  it('waits for the create, then deletes the id the server minted', async () => {
    const { result } = renderHook(useReading, { wrapper: ReadingProvider })
    await open(result, 'doc-a', [])

    // The create is in flight and will succeed with the server's own id.
    let resolveCreate!: (value: Response) => void
    api.fetch.mockImplementationOnce(
      () =>
        new Promise<Response>(resolve => {
          resolveCreate = resolve
        })
    )
    const optimistic = { ...mark('pending-1'), quote: 'fresh', updated_at: 10 }
    let saving!: Promise<boolean>
    act(() => {
      saving = result.current.saveMark({ locator: 1, quote: 'fresh' }, optimistic)
    })
    expect(result.current.annotations.map(row => row.annotation_id)).toEqual(['pending-1'])

    // The reader deletes it before the PUT has returned.
    let removing!: Promise<boolean>
    act(() => {
      removing = result.current.removeMark(result.current.annotations[0])
    })

    // The create lands with the real id; the delete must now name that id.
    api.fetch.mockImplementationOnce(() => Promise.resolve(new Response('{}')))
    await act(async () => {
      resolveCreate(
        new Response(JSON.stringify({ ...mark('real-1'), quote: 'fresh', updated_at: 123 }))
      )
      await saving
      await removing
      await flush()
    })

    const calls = api.fetch.mock.calls.map(call => [
      String(call[1]?.method ?? 'GET'),
      String(call[0]),
    ])
    // A DELETE went out, and it named the server's id — never `pending-1`.
    const deletes = calls.filter(([method]) => method === 'DELETE')
    expect(deletes).toHaveLength(1)
    expect(deletes[0][1]).toContain('real-1')
    expect(deletes[0][1]).not.toContain('pending-1')
    expect(deletes[0][1]).toContain('expected_updated_at=123')
    expect(result.current.annotations).toEqual([])
  })
})

it('rejects overlapping saves without stranding a delete waiting for the first save', async () => {
  const { result } = renderHook(useReading, { wrapper: ReadingProvider })
  const original = mark('a1')
  await open(result, 'doc-a', [original])
  let finish!: (response: Response) => void
  api.fetch.mockImplementationOnce(
    () =>
      new Promise<Response>(resolve => {
        finish = resolve
      })
  )
  let first!: Promise<boolean>
  let removing!: Promise<boolean>
  act(() => {
    first = result.current.saveMark(
      { locator: 1, annotation_id: 'a1', note: 'first' },
      { ...original, note: 'first' }
    )
  })
  act(() => {
    removing = result.current.removeMark(original)
  })
  let second = true
  await act(async () => {
    second = await result.current.saveMark(
      { locator: 1, annotation_id: 'a1', note: 'second' },
      { ...original, note: 'second' }
    )
  })
  expect(second).toBe(false)
  api.fetch.mockResolvedValueOnce(new Response('{}'))
  await act(async () => {
    finish(new Response(JSON.stringify({ ...original, note: 'first', updated_at: 99 })))
    expect(await first).toBe(true)
    expect(await removing).toBe(true)
  })
  const deletes = api.fetch.mock.calls.filter(call => call[1]?.method === 'DELETE')
  expect(deletes).toHaveLength(1)
  expect(String(deletes[0][0])).toContain('expected_updated_at=99')
})

it("an old document save cannot settle a new save's queued deletion", async () => {
  const { result } = renderHook(useReading, { wrapper: ReadingProvider })
  const original = mark('a1')
  await open(result, 'doc-a', [original])
  let finishOld!: (response: Response) => void
  api.fetch.mockImplementationOnce(
    () =>
      new Promise<Response>(resolve => {
        finishOld = resolve
      })
  )
  let oldSave!: Promise<boolean>
  act(() => {
    oldSave = result.current.saveMark(
      { locator: 1, annotation_id: 'a1', note: 'old request' },
      { ...original, note: 'old request' }
    )
  })
  act(() => result.current.closeMaterial())
  await open(result, 'doc-a', [original])
  let finishNew!: (response: Response) => void
  api.fetch.mockImplementationOnce(
    () =>
      new Promise<Response>(resolve => {
        finishNew = resolve
      })
  )
  let newSave!: Promise<boolean>
  let removing!: Promise<boolean>
  act(() => {
    newSave = result.current.saveMark(
      { locator: 1, annotation_id: 'a1', note: 'new request' },
      { ...original, note: 'new request' }
    )
  })
  act(() => {
    removing = result.current.removeMark(original)
  })
  await act(async () => {
    finishOld(new Response(JSON.stringify({ ...original, note: 'old request', updated_at: 10 })))
    await oldSave
  })
  expect(api.fetch.mock.calls.filter(call => call[1]?.method === 'DELETE')).toHaveLength(0)
  api.fetch.mockResolvedValueOnce(new Response('{}'))
  await act(async () => {
    finishNew(new Response(JSON.stringify({ ...original, note: 'new request', updated_at: 20 })))
    await newSave
    expect(await removing).toBe(true)
  })
  const deletes = api.fetch.mock.calls.filter(call => call[1]?.method === 'DELETE')
  expect(deletes).toHaveLength(1)
  expect(String(deletes[0][0])).toContain('expected_updated_at=20')
})

it("an old scope's failed delete cannot remove the new scope's tombstone", async () => {
  const { result } = renderHook(useReading, { wrapper: ReadingProvider })
  const original = mark('a1')
  await open(result, 'doc-a', [original])
  let failOld!: (error: Error) => void
  api.fetch.mockImplementationOnce(
    () =>
      new Promise<Response>((_resolve, reject) => {
        failOld = reject
      })
  )
  let oldDelete!: Promise<boolean>
  act(() => {
    oldDelete = result.current.removeMark(original)
  })
  act(() => result.current.closeMaterial())
  await open(result, 'doc-a', [original])
  let finishNew!: (response: Response) => void
  api.fetch.mockImplementationOnce(
    () =>
      new Promise<Response>(resolve => {
        finishNew = resolve
      })
  )
  let newDelete!: Promise<boolean>
  act(() => {
    newDelete = result.current.removeMark(original)
  })
  await act(async () => {
    failOld(new Error('old failure'))
    expect(await oldDelete).toBe(false)
  })
  api.fetch.mockResolvedValueOnce(response([original]))
  await act(async () => {
    broadcast('doc-a')
    await flush()
  })
  expect(result.current.annotations).toEqual([])
  await act(async () => {
    finishNew(new Response('{}'))
    expect(await newDelete).toBe(true)
  })
  expect(result.current.annotations).toEqual([])
})

it('dispatches one delete when the same row is removed twice before a render', async () => {
  const { result } = renderHook(useReading, { wrapper: ReadingProvider })
  const original = mark('a1')
  await open(result, 'doc-a', [original])
  let finish!: (response: Response) => void
  api.fetch.mockImplementationOnce(
    () =>
      new Promise<Response>(resolve => {
        finish = resolve
      })
  )
  let first!: Promise<boolean>
  let second!: Promise<boolean>
  act(() => {
    first = result.current.removeMark(original)
    second = result.current.removeMark(original)
  })
  expect(api.fetch.mock.calls.filter(call => call[1]?.method === 'DELETE')).toHaveLength(1)
  await act(async () => {
    finish(new Response('{}'))
    await first
    await second
  })
})

it('rejects a second deletion while the failed first deletion is reconciling', async () => {
  const { result } = renderHook(useReading, { wrapper: ReadingProvider })
  const original = mark('a1')
  await open(result, 'doc-a', [original])
  let failRefresh!: (error: Error) => void
  api.fetch.mockRejectedValueOnce(new Error('delete failed'))
  api.fetch.mockImplementationOnce(() => new Promise<Response>((_resolve, reject) => {
    failRefresh = reject
  }))
  let first!: Promise<boolean>
  act(() => { first = result.current.removeMark(original) })
  await act(async () => { await flush() })
  api.fetch.mockResolvedValueOnce(new Response('{}'))
  await act(async () => {
    expect(await result.current.removeMark(original)).toBe(false)
  })
  expect(api.fetch.mock.calls.filter(call => call[1]?.method === 'DELETE')).toHaveLength(1)
  await act(async () => {
    failRefresh(new Error('refresh failed'))
    expect(await first).toBe(false)
  })
  expect(result.current.annotations).toEqual([original])
})
