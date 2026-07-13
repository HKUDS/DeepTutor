'use client'

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import Image from 'next/image'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useAppShell } from '@/context/AppShellContext'
import {
  BookOpen,
  Bot,
  Github,
  LayoutGrid,
  Library,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  PenLine,
  Plus,
  Settings,
  type LucideIcon,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import SessionList from '@/components/SessionList'
import { TutorBotRecent } from '@/components/sidebar/TutorBotRecent'
import { VersionBadge } from '@/components/sidebar/VersionBadge'
import type { SessionSummary } from '@/lib/session-api'
import clsx from 'clsx'

interface NavEntry {
  href: string
  label: string
  icon: LucideIcon
}

const PRIMARY_NAV: NavEntry[] = [
  { href: '/chat', label: 'Chat', icon: MessageSquare },
  { href: '/agents', label: 'TutorBot', icon: Bot },
  { href: '/co-writer', label: 'Co-Writer', icon: PenLine },
  { href: '/book', label: 'Book', icon: Library },
  { href: '/knowledge', label: 'Knowledge', icon: BookOpen },
  { href: '/space', label: 'Space', icon: LayoutGrid },
]

const SECONDARY_NAV: NavEntry[] = [{ href: '/settings', label: 'Settings', icon: Settings }]
const DEFAULT_SESSION_VIEWPORT_CLASS_NAME = 'max-h-[112px]'
const GITHUB_REPO_URL = 'https://github.com/HKUDS/DeepTutor'
const DESKTOP_CHROME_KEY = 'deeptutor.desktop'
const DESKTOP_PLATFORM_KEY = 'deeptutor.platform'

interface SidebarShellProps {
  children?: ReactNode
  workspace?: boolean
  sessions?: SessionSummary[]
  activeSessionId?: string | null
  loadingSessions?: boolean
  showSessions?: boolean
  sessionViewportClassName?: string
  onNewChat?: () => void
  onSelectSession?: (sessionId: string) => void | Promise<void>
  onRenameSession?: (sessionId: string, title: string) => void | Promise<void>
  onDeleteSession?: (sessionId: string) => void | Promise<void>
  footerSlot?: ReactNode
}

interface ElectronWindow {
  minimize: () => Promise<void>
  maximize: () => Promise<void>
  close: () => Promise<void>
  isMaximized: () => Promise<boolean>
  onMaximizeChange: (callback: (isMaximized: boolean) => void) => () => void
}

interface ElectronAPI {
  window: ElectronWindow
  app?: {
    getVersion: () => Promise<string>
    getPlatform: () => Promise<string>
  }
}

declare global {
  interface Window {
    electron?: ElectronAPI
  }
}

export function SidebarShell({
  children,
  workspace = false,
  sessions = [],
  activeSessionId = null,
  loadingSessions = false,
  showSessions = false,
  sessionViewportClassName = DEFAULT_SESSION_VIEWPORT_CLASS_NAME,
  onNewChat,
  onSelectSession,
  onRenameSession,
  onDeleteSession,
  footerSlot,
}: SidebarShellProps) {
  const pathname = usePathname()
  const router = useRouter()
  const { t } = useTranslation()
  const { sidebarCollapsed: collapsed, setSidebarCollapsed: setCollapsed } = useAppShell()

  const [isDesktopClient, setIsDesktopClient] = useState(false)
  const [isMacDesktop, setIsMacDesktop] = useState(false)

  useEffect(() => {
    // Detect desktop mode before React has fully settled. The desktop preload
    // exposes globals and writes localStorage; the query param is a final
    // fallback for dev startup and deep links.
    const detect = () => {
      const w = window as Window & {
        __DEEPTUTOR_DESKTOP__?: boolean
        __DEEPTUTOR_PLATFORM__?: string
      }
      const desktopParam = new URLSearchParams(window.location.search).get('desktop')
      let storedDesktop = false
      let storedPlatform = ''
      try {
        storedDesktop = window.localStorage.getItem(DESKTOP_CHROME_KEY) === '1'
        storedPlatform = window.localStorage.getItem(DESKTOP_PLATFORM_KEY) ?? ''
      } catch (_error) {
        // Ignore storage failures; injected globals and URL params still work.
      }
      const isDesktop =
        w.__DEEPTUTOR_DESKTOP__ === true ||
        desktopParam === '1' ||
        desktopParam === 'true' ||
        storedDesktop
      const platform = (w.__DEEPTUTOR_PLATFORM__ || storedPlatform || window.navigator.platform || '').toLowerCase()
      setIsDesktopClient(isDesktop)
      setIsMacDesktop(isDesktop && platform.includes('mac'))
    }
    detect()
    const raf = requestAnimationFrame(detect)
    const timeout = window.setTimeout(detect, 250)
    return () => {
      cancelAnimationFrame(raf)
      window.clearTimeout(timeout)
    }
  }, [])

  const [desktopSidebarCollapsed, setDesktopSidebarCollapsed] = useState(false)
  const effectiveCollapsed = isDesktopClient ? desktopSidebarCollapsed : collapsed
  const setEffectiveCollapsed = isDesktopClient ? setDesktopSidebarCollapsed : setCollapsed

  const [isMaximized, setIsMaximized] = useState(false)

  useEffect(() => {
    if (!isDesktopClient || !window.electron?.window) return
    window.electron.window.isMaximized().then(setIsMaximized)
    const unsubscribe = window.electron.window.onMaximizeChange(setIsMaximized)
    return unsubscribe
  }, [isDesktopClient])

  const handleMinimize = useCallback(() => {
    window.electron?.window?.minimize()
  }, [])

  const handleMaximize = useCallback(() => {
    window.electron?.window?.maximize()
  }, [])

  const handleClose = useCallback(() => {
    window.electron?.window?.close()
  }, [])

  const handleNewChat = () => {
    if (onNewChat) {
      onNewChat()
      return
    }
    router.push('/chat')
  }

  const SIDEBAR_MIN = 160
  const SIDEBAR_MAX = 320
  const SIDEBAR_DEFAULT = 220
  const MAIN_MIN = 480
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT)
  const isResizing = useRef(false)

  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      isResizing.current = true
      const startX = e.clientX
      const startW = sidebarWidth

      const onMove = (ev: MouseEvent) => {
        if (!isResizing.current) return
        const containerWidth = window.innerWidth
        const newW = Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, startW + (ev.clientX - startX)))
        if (containerWidth - newW >= MAIN_MIN) {
          setSidebarWidth(newW)
        }
      }

      const onUp = () => {
        isResizing.current = false
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }

      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    [sidebarWidth]
  )

  const glassBackground = isDesktopClient ? 'rgba(255, 255, 255, 0.08)' : undefined

  return (
    <div className={`flex h-full relative overflow-hidden ${workspace ? 'w-full' : ''}`}>
      <aside
        className={clsx(
          'flex h-full shrink-0 flex-col transition-all duration-200',
          isDesktopClient ? 'bg-transparent' : 'bg-[var(--secondary)]'
        )}
        style={
          isDesktopClient
            ? ({
                width: effectiveCollapsed ? 60 : sidebarWidth,
                background: glassBackground,
                WebkitAppRegion: 'drag' as const,
              } as React.CSSProperties)
            : { width: effectiveCollapsed ? 60 : sidebarWidth }
        }
      >
        {isMacDesktop && !effectiveCollapsed && (
          <div
            data-desktop-drag-region
            className="h-[40px] shrink-0"
            style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
            onDoubleClick={() => {
              const w = window as Window & { __DEEPTUTOR_MAXIMIZE__?: () => void }
              w.__DEEPTUTOR_MAXIMIZE__?.()
            }}
          />
        )}

        <div
          className={clsx(
            'shrink-0 flex items-center mb-[30px]',
            isMacDesktop && !effectiveCollapsed ? 'h-0' : 'h-14',
            isMacDesktop && effectiveCollapsed && 'mt-[40px]'
          )}
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          {effectiveCollapsed ? (
            <div className="w-full flex justify-center">
              <button
                onClick={() => setEffectiveCollapsed(false)}
                className="flex items-center justify-center h-9 w-9 rounded-lg text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--accent)]/20 transition-colors"
                aria-label={t('Expand sidebar')}
              >
                <PanelLeftOpen size={16} />
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-between w-full px-4">
              <Link href="/" className="group flex items-center gap-2">
                <Image
                  src="/logo-ver2.png"
                  alt="DeepTutor"
                  width={22}
                  height={22}
                  className="h-[22px] w-[22px] transition-transform duration-200 group-hover:scale-105"
                />
                <span className="text-[16px] font-semibold leading-none tracking-[-0.02em] text-[var(--foreground)]">
                  DeepTutor
                </span>
              </Link>
              <button
                onClick={() => setEffectiveCollapsed(true)}
                className="rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                aria-label={t('Collapse sidebar')}
              >
                <PanelLeftClose size={15} />
              </button>
            </div>
          )}
        </div>

        {!effectiveCollapsed && (
          <>
            <nav className="flex-1 min-h-0 overflow-y-auto px-2 pt-1">
              <div className="space-y-px">
                <button
                  onClick={handleNewChat}
                  className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--accent)]/20 hover:text-[var(--foreground)]"
                >
                  <Plus size={16} strokeWidth={2} />
                  <span>{t('New Chat')}</span>
                </button>

                {PRIMARY_NAV.map(item => {
                  const active = pathname.startsWith(item.href)
                  const hasSessionsBelow =
                    item.href === '/chat' &&
                    showSessions &&
                    onSelectSession &&
                    onRenameSession &&
                    onDeleteSession
                  const hasBots = item.href === '/agents'
                  return (
                    <div key={item.href}>
                      <Link
                        href={item.href}
                        className={clsx(
                          'flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors',
                          active
                            ? 'bg-[var(--accent)]/20 font-medium text-[var(--foreground)]'
                            : 'text-[var(--muted-foreground)] hover:bg-[var(--accent)]/10 hover:text-[var(--foreground)]'
                        )}
                      >
                        <item.icon size={16} strokeWidth={active ? 1.9 : 1.5} />
                        <span>{t(item.label)}</span>
                      </Link>
                      {hasSessionsBelow && (
                        <div className={clsx(sessionViewportClassName, 'overflow-y-auto')}>
                          <SessionList
                            sessions={sessions}
                            activeSessionId={activeSessionId}
                            loading={loadingSessions}
                            onSelect={onSelectSession}
                            onRename={onRenameSession}
                            onDelete={onDeleteSession}
                            compact
                          />
                        </div>
                      )}
                      {hasBots && <TutorBotRecent />}
                    </div>
                  )
                })}
              </div>
            </nav>

            <div className="border-t border-[var(--border)]/40 px-2 py-2">
              {SECONDARY_NAV.map(item => {
                const active = pathname.startsWith(item.href)
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={clsx(
                      'flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors',
                      active
                        ? 'bg-[var(--accent)]/20 font-medium text-[var(--foreground)]'
                        : 'text-[var(--muted-foreground)] hover:bg-[var(--accent)]/10 hover:text-[var(--foreground)]'
                    )}
                  >
                    <item.icon size={16} strokeWidth={active ? 1.9 : 1.5} />
                    <span>{t(item.label)}</span>
                  </Link>
                )
              })}
              {footerSlot}
              <div className="mt-0.5 flex items-center gap-0.5">
                <VersionBadge />
                <a
                  href={GITHUB_REPO_URL}
                  target="_blank"
                  rel="noreferrer noopener"
                  title="GitHub"
                  aria-label="GitHub"
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)]/55 transition-colors hover:bg-[var(--accent)]/10 hover:text-[var(--foreground)]"
                >
                  <Github size={13} strokeWidth={1.7} />
                </a>
              </div>
            </div>
          </>
        )}

        {effectiveCollapsed && (
          <div
            className="flex-1 flex flex-col items-center gap-1 px-1.5 py-2"
            style={isMacDesktop ? { paddingTop: '40px' } : undefined}
          >
            <button
              onClick={handleNewChat}
              className="flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--border)]/50 bg-[var(--background)]/40 text-[var(--foreground)] shadow-sm transition-all hover:bg-[var(--background)]/80"
              aria-label={t('New Chat')}
            >
              <Plus size={16} strokeWidth={2.2} />
            </button>

            <div className="my-1.5 h-px w-7 bg-[var(--border)]/40" />

            {PRIMARY_NAV.map(item => {
              const active = pathname.startsWith(item.href)
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  title={t(item.label) as string}
                  className={clsx(
                    'relative flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-150',
                    active
                      ? 'bg-[var(--accent)]/20 text-[var(--foreground)]'
                      : 'text-[var(--muted-foreground)] hover:bg-[var(--accent)]/10 hover:text-[var(--foreground)]'
                  )}
                >
                  {active && (
                    <span className="absolute -left-1.5 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-[var(--foreground)]/80" />
                  )}
                  <item.icon size={18} strokeWidth={active ? 2 : 1.6} />
                </Link>
              )
            })}

            <div className="flex-1" />

            {SECONDARY_NAV.map(item => {
              const active = pathname.startsWith(item.href)
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  title={t(item.label) as string}
                  className={clsx(
                    'relative flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-150',
                    active
                      ? 'bg-[var(--accent)]/20 text-[var(--foreground)]'
                      : 'text-[var(--muted-foreground)] hover:bg-[var(--accent)]/10 hover:text-[var(--foreground)]'
                  )}
                >
                  {active && (
                    <span className="absolute -left-1.5 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-[var(--foreground)]/80" />
                  )}
                  <item.icon size={18} strokeWidth={active ? 2 : 1.6} />
                </Link>
              )
            })}

            <a
              href={GITHUB_REPO_URL}
              target="_blank"
              rel="noreferrer noopener"
              title="GitHub"
              aria-label="GitHub"
              className="flex h-9 w-9 items-center justify-center rounded-xl text-[var(--muted-foreground)]/70 transition-colors hover:bg-[var(--accent)]/10 hover:text-[var(--foreground)]"
            >
              <Github size={15} strokeWidth={1.6} />
            </a>
            <VersionBadge collapsed />
          </div>
        )}
      </aside>

      {!effectiveCollapsed && (
        <div
          onMouseDown={handleResizeStart}
          className="hidden md:block w-px shrink-0 cursor-col-resize group relative z-10"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          <div className="absolute inset-y-0 -left-1.5 -right-1.5 hover:bg-[var(--accent)]/20 transition-colors" />
        </div>
      )}

      <main
        className="relative min-w-0 flex-1 overflow-hidden h-full"
        style={{ background: 'var(--background)' }}
      >
        <div
          className={clsx(
            'relative flex h-full min-w-0 flex-col overflow-hidden',
            isDesktopClient ? 'bg-[var(--background)] rounded-l-xl' : 'bg-[var(--background)]'
          )}
        >
          {children}
        </div>
      </main>
    </div>
  )
}
