'use client'

import { useState, useEffect } from 'react'
import { Minus, Square, X, Maximize2 } from 'lucide-react'
import clsx from 'clsx'

interface ElectronWindow {
  minimize: () => Promise<void>
  maximize: () => Promise<void>
  close: () => Promise<void>
  isMaximized: () => Promise<boolean>
  onMaximizeChange: (callback: (isMaximized: boolean) => void) => () => void
}

interface ElectronApp {
  getVersion: () => Promise<string>
  getPlatform: () => Promise<string>
}

interface ElectronAPI {
  window: ElectronWindow
  app?: ElectronApp
}

declare global {
  interface Window {
    electron?: ElectronAPI
  }
}

export default function TitleBar() {
  const [isMaximized, setIsMaximized] = useState(false)
  const [platform, setPlatform] = useState<string>('darwin')
  const [isDesktop, setIsDesktop] = useState(false)

  useEffect(() => {
    // Check if running in desktop
    const checkDesktop = () => {
      const hasElectron = typeof window !== 'undefined' && window.electron !== undefined
      setIsDesktop(hasElectron)
      return hasElectron
    }

    if (checkDesktop()) {
      // Check initial maximized state
      window.electron?.window?.isMaximized().then(setIsMaximized)
      window.electron?.window?.onMaximizeChange(setIsMaximized)

      // Get platform
      window.electron?.app?.getPlatform().then(setPlatform)
    }
  }, [])

  const handleMinimize = () => {
    window.electron?.window?.minimize()
  }

  const handleMaximize = () => {
    window.electron?.window?.maximize()
  }

  const handleClose = () => {
    window.electron?.window?.close()
  }

  const isMac = platform === 'darwin'

  // Only render in desktop mode
  if (!isDesktop) {
    return null
  }

  return (
    <div
      className={clsx(
        'flex items-center justify-between h-10 px-4 shrink-0',
        'bg-[var(--background)] border-b border-[var(--border)]',
        'select-none'
      )}
      style={{
        WebkitAppRegion: 'drag' as React.CSSProperties['WebkitAppRegion'],
      }}
    >
      {/* Left: App title or traffic lights (macOS) */}
      <div className="flex items-center gap-3">
        {isMac && (
          <div
            className="flex items-center gap-2"
            style={{ WebkitAppRegion: 'no-drag' as React.CSSProperties['WebkitAppRegion'] }}
          >
            <button
              onClick={handleClose}
              className="w-3 h-3 rounded-full bg-red-500 hover:bg-red-600 transition-colors"
              aria-label="Close"
            />
            <button
              onClick={handleMinimize}
              className="w-3 h-3 rounded-full bg-yellow-500 hover:bg-yellow-600 transition-colors"
              aria-label="Minimize"
            />
            <button
              onClick={handleMaximize}
              className="w-3 h-3 rounded-full bg-green-500 hover:bg-green-600 transition-colors"
              aria-label="Maximize"
            />
          </div>
        )}
        {!isMac && (
          <span className="text-sm font-semibold text-[var(--foreground)]">
            DeepTutor
          </span>
        )}
      </div>

      {/* Center: Draggable area (Windows shows title here) */}
      <div className="flex-1" />

      {/* Right: Window controls (Windows only) */}
      {!isMac && (
        <div
          className="flex items-center gap-1"
          style={{ WebkitAppRegion: 'no-drag' as React.CSSProperties['WebkitAppRegion'] }}
        >
          <button
            onClick={handleMinimize}
            className={clsx(
              'flex items-center justify-center w-10 h-8 rounded hover:bg-[var(--accent)]',
              'text-[var(--muted-foreground)] hover:text-[var(--foreground)]',
              'transition-colors'
            )}
            aria-label="Minimize"
          >
            <Minus size={16} />
          </button>
          <button
            onClick={handleMaximize}
            className={clsx(
              'flex items-center justify-center w-10 h-8 rounded hover:bg-[var(--accent)]',
              'text-[var(--muted-foreground)] hover:text-[var(--foreground)]',
              'transition-colors'
            )}
            aria-label={isMaximized ? 'Restore' : 'Maximize'}
          >
            {isMaximized ? <Square size={14} /> : <Maximize2 size={16} />}
          </button>
          <button
            onClick={handleClose}
            className={clsx(
              'flex items-center justify-center w-10 h-8 rounded',
              'text-[var(--muted-foreground)] hover:bg-red-500 hover:text-white',
              'transition-colors'
            )}
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  )
}
