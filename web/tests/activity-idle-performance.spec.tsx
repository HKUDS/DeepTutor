import { act, render } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ActivityMark } from '@/components/activity/ActivityMark'
import { ActivityHeader } from '@/components/activity/ActivityHeader'
import { SessionAvatar } from '@/components/sidebar/SessionAvatar'
import { useResolvedDark, useResolvedInk } from '@/vendor/thinking-orbs/theme'

vi.mock('@/vendor/thinking-orbs/engine/registry', () => ({
  MODE_DRAWS: new Proxy({}, { get: () => () => {} }),
}))
vi.mock('@/lib/task-board-store', () => ({ useTaskBoard: () => ({ board: null }) }))

const intersections = new Set<IntersectionObserverCallback>()

beforeEach(() => {
  intersections.clear()
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      callback: IntersectionObserverCallback
      constructor(callback: IntersectionObserverCallback) {
        this.callback = callback
        intersections.add(callback)
      }
      observe() {}
      disconnect() {
        intersections.delete(this.callback)
      }
    }
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    setTransform() {},
    clearRect() {},
  } as unknown as CanvasRenderingContext2D)
  vi.stubGlobal(
    'requestAnimationFrame',
    vi.fn(() => 1)
  )
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
})

afterEach(() => vi.unstubAllGlobals())

function intersect() {
  act(() => {
    for (const callback of intersections)
      callback([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver)
  })
}

function ThemeProbe() {
  const ref = useRef<HTMLSpanElement>(null)
  const dark = useResolvedDark('auto', ref)
  const ink = useResolvedInk(ref)
  return <span ref={ref} data-dark={String(dark)} data-ink={ink} />
}

describe('idle activity cost', () => {
  it('does not animate twenty settled markers', () => {
    render(
      <>
        {Array.from({ length: 20 }, (_, i) => (
          <ActivityMark key={i} state="done" />
        ))}
      </>
    )
    intersect()
    expect(requestAnimationFrame).not.toHaveBeenCalled()
  })

  it('stops the live marker clock when work settles and restarts for new work', () => {
    const view = render(<ActivityMark state="running" />)
    intersect()
    expect(requestAnimationFrame).toHaveBeenCalled()
    vi.mocked(requestAnimationFrame).mockClear()
    vi.mocked(cancelAnimationFrame).mockClear()
    view.rerender(<ActivityMark state="done" />)
    intersect()
    expect(cancelAnimationFrame).toHaveBeenCalled()
    expect(requestAnimationFrame).not.toHaveBeenCalled()
    view.rerender(<ActivityMark state="running" />)
    intersect()
    expect(requestAnimationFrame).toHaveBeenCalled()
  })

  it('keeps a completed activity header static', () => {
    render(<ActivityHeader orb="breathing" label="Completed" settled />)
    intersect()
    expect(requestAnimationFrame).not.toHaveBeenCalled()
  })

  it('keeps idle sidebar avatars static while allowing running sessions to animate', () => {
    const view = render(<SessionAvatar sessionId="example" workspaceId="" mark="idle" />)
    intersect()
    expect(requestAnimationFrame).not.toHaveBeenCalled()
    view.rerender(<SessionAvatar sessionId="example" workspaceId="" mark="running" />)
    intersect()
    expect(requestAnimationFrame).toHaveBeenCalled()
  })

  it('does not reread every orb style when an unrelated input changes class', async () => {
    const view = render(
      <>
        <input />
        {Array.from({ length: 20 }, (_, i) => (
          <ThemeProbe key={i} />
        ))}
      </>
    )
    const computed = vi.spyOn(window, 'getComputedStyle')
    await act(async () => {
      view.container.querySelector('input')!.className = 'typing'
    })
    expect(computed).not.toHaveBeenCalled()
  })

  it('still follows class and data-theme changes on its ancestors', async () => {
    const view = render(
      <div data-testid="ancestor">
        <ThemeProbe />
      </div>
    )
    const parent = view.getByTestId('ancestor')
    const probe = parent.firstElementChild!
    const computed = vi.spyOn(window, 'getComputedStyle')
    await act(async () => {
      parent.setAttribute('data-theme', 'light')
    })
    expect(probe.getAttribute('data-dark')).toBe('false')
    expect(computed).toHaveBeenCalled()
    computed.mockClear()
    await act(async () => {
      parent.className = 'another-ink'
    })
    expect(computed).toHaveBeenCalled()
  })

  it('disconnects theme observers on unmount', async () => {
    const view = render(<ThemeProbe />)
    view.unmount()
    const computed = vi.spyOn(window, 'getComputedStyle')
    const previous = document.documentElement.getAttribute('data-theme')
    await act(async () => {
      document.documentElement.setAttribute('data-theme', 'light')
    })
    expect(computed).not.toHaveBeenCalled()
    if (previous === null) document.documentElement.removeAttribute('data-theme')
    else document.documentElement.setAttribute('data-theme', previous)
  })
})
