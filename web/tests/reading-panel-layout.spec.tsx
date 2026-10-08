import React, { useState } from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadingPanelSeparator } from '@/components/reading/workspace/ReadingPanelSeparator'
import {
  readingPanelBounds,
  useReadingPanelLayout,
} from '@/components/reading/workspace/useReadingPanelLayout'

let frame = 1200
let observers: { resize: () => void; disconnect: ReturnType<typeof vi.fn> }[] = []

function Harness({
  loading = false,
  navigatorOpen = true,
}: {
  loading?: boolean
  navigatorOpen?: boolean
}) {
  const { gridRef, ...panels } = useReadingPanelLayout({ enabled: true, navigatorOpen, companionOpen: true })
  if (loading) return <div>Loading</div>
  return (
    <div ref={gridRef} style={panels.gridStyle} data-testid="grid">
      <output data-testid="navigator">{String(panels.navigatorOpen)}</output>
      <button onClick={panels.toggleFocus}>Focus</button>
      {panels.showNavigatorHandle && (
        <ReadingPanelSeparator
          label="Navigator"
          width={panels.navigatorWidth}
          min={panels.navigatorMin}
          max={panels.navigatorMax}
          direction={1}
          onResize={panels.resizeNavigator}
        />
      )}
      {panels.showCompanionHandle && (
        <ReadingPanelSeparator
          label="Companion"
          width={panels.companionWidth}
          min={panels.companionMin}
          max={panels.companionMax}
          direction={-1}
          onResize={panels.resizeCompanion}
        />
      )}
    </div>
  )
}

beforeEach(() => {
  frame = 1200
  observers = []
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => frame)
  vi.stubGlobal(
    'ResizeObserver',
    class {
      disconnect = vi.fn()
      constructor(resize: () => void) {
        observers.push({ resize, disconnect: this.disconnect })
      }
      observe() {}
    }
  )
  vi.stubGlobal(
    'PointerEvent',
    class extends MouseEvent {
      pointerId: number
      constructor(type: string, options: PointerEventInit) {
        super(type, options)
        this.pointerId = options.pointerId ?? 1
      }
    }
  )
  Object.defineProperties(HTMLElement.prototype, {
    setPointerCapture: { configurable: true, value: vi.fn() },
    hasPointerCapture: { configurable: true, value: vi.fn(() => true) },
    releasePointerCapture: { configurable: true, value: vi.fn() },
  })
})
afterEach(() => vi.unstubAllGlobals())

function measure() {
  act(() => observers.at(-1)?.resize())
}

describe('reading panel layout', () => {
  it('observes a grid appearing after loading and disconnects on removal', () => {
    const view = render(<Harness loading />)
    expect(observers).toHaveLength(0)
    view.rerender(<Harness />)
    expect(observers).toHaveLength(1)
    measure()
    expect(screen.getByRole('separator', { name: 'Companion' })).toHaveAttribute(
      'aria-valuenow',
      '380'
    )
    frame = 900
    measure()
    expect(screen.getByRole('separator', { name: 'Companion' })).toHaveAttribute(
      'aria-valuenow',
      '320'
    )
    view.rerender(<Harness loading />)
    expect(observers[0].disconnect).toHaveBeenCalledOnce()
  })

  it.each([500, 700, 854, 900, 1600])('fits both panels inside a %ipx container', width => {
    const bounds = readingPanelBounds(width, true, true, 400, 2200)
    const reader = width - bounds.navigatorWidth - bounds.companionWidth - 10
    expect(reader).toBeGreaterThanOrEqual(Math.min(360, width / 2))
    expect(bounds.navigatorWidth).toBeLessThanOrEqual(bounds.navigatorMax)
    expect(bounds.companionWidth).toBeLessThanOrEqual(bounds.companionMax)
    if (width >= 854) {
      expect(bounds.navigatorWidth).toBeGreaterThanOrEqual(184)
      expect(bounds.companionWidth).toBeGreaterThanOrEqual(300)
    }
  })

  it.each([true, false])(
    'restores widths and the previous navigator state (%s) after focus',
    navigatorOpen => {
      localStorage.setItem('dt.reader.companionWidth', '420')
      render(<Harness navigatorOpen={navigatorOpen} />)
      measure()
      fireEvent.click(screen.getByRole('button', { name: 'Focus' }))
      expect(screen.getByTestId('navigator')).toHaveTextContent('false')
      const handle = screen.getByRole('separator', { name: 'Companion' })
      expect(handle).toHaveAttribute('aria-valuenow', '600')
      fireEvent.keyDown(handle, { key: 'ArrowLeft' })
      expect(handle).toHaveAttribute('aria-valuenow', '610')
      expect(localStorage.getItem('dt.reader.companionWidth')).toBe('420')
      fireEvent.click(screen.getByRole('button', { name: 'Focus' }))
      expect(screen.getByTestId('navigator')).toHaveTextContent(String(navigatorOpen))
      expect(handle).toHaveAttribute('aria-valuenow', '420')
    }
  )

  it('supports keyboard limits and coordinates both separator widths', () => {
    render(<Harness />)
    measure()
    const nav = screen.getByRole('separator', { name: 'Navigator' })
    const companion = screen.getByRole('separator', { name: 'Companion' })
    fireEvent.keyDown(companion, { key: 'End' })
    expect(companion).toHaveAttribute('aria-valuenow', '620')
    fireEvent.keyDown(nav, { key: 'End' })
    expect(nav).toHaveAttribute('aria-valuenow', '210')
    fireEvent.keyDown(companion, { key: 'Home' })
    fireEvent.keyDown(nav, { key: 'End' })
    expect(nav).toHaveAttribute('aria-valuenow', '400')
    expect(companion).toHaveAttribute('aria-valuenow', '300')
    expect(nav).toHaveAttribute('tabindex', '0')
  })

  it('ends a captured drag on cancel and restores body styles on unmount', () => {
    function Resizable() {
      const [width, resize] = useState(300)
      return (
        <ReadingPanelSeparator
          label="Resize"
          width={width}
          min={100}
          max={600}
          direction={1}
          onResize={resize}
        />
      )
    }
    document.body.style.cursor = 'crosshair'
    document.body.style.userSelect = 'text'
    const view = render(<Resizable />)
    const handle = screen.getByRole('separator')
    fireEvent.pointerDown(handle, { button: 0, pointerId: 7, clientX: 200 })
    fireEvent.pointerMove(handle, { pointerId: 8, clientX: 250 })
    expect(handle).toHaveAttribute('aria-valuenow', '300')
    fireEvent.pointerMove(handle, { pointerId: 7, clientX: 250 })
    expect(handle).toHaveAttribute('aria-valuenow', '350')
    fireEvent.pointerCancel(handle, { pointerId: 7 })
    fireEvent.pointerMove(handle, { pointerId: 7, clientX: 400 })
    expect(handle).toHaveAttribute('aria-valuenow', '350')
    expect(document.body.style.cursor).toBe('crosshair')
    expect(handle.releasePointerCapture).toHaveBeenCalledWith(7)
    fireEvent.pointerDown(handle, { button: 0, pointerId: 9, clientX: 200 })
    expect(document.body.style.cursor).toBe('col-resize')
    view.unmount()
    expect(document.body.style.cursor).toBe('crosshair')
    expect(document.body.style.userSelect).toBe('text')
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  })
})
