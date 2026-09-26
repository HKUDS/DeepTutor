'use client'

import { useEffect, useRef, useState } from 'react'
import { browserStorage } from '@/shared/storage'
import { usePathname, useRouter } from 'next/navigation'
import { ArrowLeft, Menu } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import SettingsNav from './SettingsNav'
import { SettingsToolbar } from './SettingsToolbar'
import { SettingsLoadStatusBanner } from './SettingsLoadStatusBanner'
import { SETTINGS_RETURN_KEY } from './SettingsReturnTracker'
import { isWideSettingsPage } from '@/features/settings/navigation/settings-pages'
import Modal from '@/components/common/Modal'
import { useSettings } from '@/features/settings/store/SettingsStore'

export default function SettingsMain({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const pathname = usePathname()
  const router = useRouter()
  const { hasUnsavedChanges, saveDraft, saving, applying, toast, setActiveSection } = useSettings()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [leaveFailed, setLeaveFailed] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  const priorPath = useRef(pathname)
  const section = pathname.split('/')[2] || 'general'

  useEffect(() => {
    setActiveSection(section)
    scroller.current?.scrollTo({ top: 0, behavior: 'instant' })
    if (priorPath.current !== pathname) content.current?.focus({ preventScroll: true })
    priorPath.current = pathname
  }, [pathname, section, setActiveSection])

  const returnToApp = () => {
    let destination = '/'
    try {
      const stored = browserStorage.readRaw('session', SETTINGS_RETURN_KEY)
      if (stored?.startsWith('/') && !stored.startsWith('//') && !stored.startsWith('/settings'))
        destination = stored
    } catch {
      /* Home is a safe fallback. */
    }
    router.push(destination)
  }
  const returnButton = (
    <button
      type="button"
      disabled={saving || applying}
      onClick={() => (hasUnsavedChanges ? setLeaving(true) : returnToApp())}
      className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] font-medium text-foreground outline-none transition-colors hover:bg-accent/60 hover:text-foreground focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-40"
    >
      <ArrowLeft size={16} strokeWidth={1.7} />
      {t('Back to app')}
    </button>
  )

  return (
    <div className="flex h-dvh overflow-hidden bg-[var(--background)]" data-settings-shell>
      <aside className="hidden w-[248px] shrink-0 flex-col border-r border-border/60 bg-[var(--background)] md:flex">
        <div className="px-2.5 pb-1.5 pt-4">{returnButton}</div>
        <SettingsNav />
      </aside>
      {/* Master–detail pages publish a wider content box; the save toolbar
          below reads the same variable so the two stay aligned. */}
      <main
        className="flex min-w-0 flex-1 flex-col overflow-hidden"
        style={
          {
            '--settings-content': isWideSettingsPage(section) ? '1280px' : '960px',
          } as React.CSSProperties
        }
      >
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-border/50 px-3 md:hidden">
          {returnButton}
          <button
            type="button"
            aria-label={t('Settings sections')}
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen(true)}
            className="rounded-md p-2 hover:bg-accent"
          >
            <Menu size={20} />
          </button>
        </div>
        <div
          ref={scroller}
          data-settings-scroll
          className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-gutter:stable]"
        >
          <div
            ref={content}
            tabIndex={-1}
            className="mx-auto w-full max-w-[var(--settings-content,960px)] px-5 pb-20 pt-8 outline-none sm:px-10 md:pt-12 lg:px-14"
          >
            <SettingsLoadStatusBanner />
            {children}
          </div>
        </div>
        <SettingsToolbar />
      </main>
      <Modal
        isOpen={mobileOpen}
        onClose={() => setMobileOpen(false)}
        title={t('Settings')}
        width="sm"
      >
        <div className="flex h-[70dvh] flex-col pt-3">
          <SettingsNav onNavigate={() => setMobileOpen(false)} />
        </div>
      </Modal>
      <Modal
        isOpen={leaving}
        onClose={() => {
          if (!saving) setLeaving(false)
        }}
        title={t('Keep your changes?')}
        width="sm"
      >
        <div className="space-y-5 p-5">
          {leaveFailed && (
            <p role="alert" className="text-sm text-red-600 dark:text-red-400">
              {toast}
            </p>
          )}
          <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
            {t(
              'Save a draft before leaving. You can return and apply it later; your current settings will keep working.'
            )}
          </p>
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              disabled={saving}
              onClick={() => setLeaving(false)}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
            >
              {t('Keep editing')}
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={async () => {
                if (await saveDraft()) returnToApp()
                else setLeaveFailed(true)
              }}
              className="rounded-lg bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)] disabled:opacity-40"
            >
              {t('Save draft and return')}
            </button>
          </div>
          <button
            type="button"
            disabled={saving}
            onClick={returnToApp}
            className="text-xs text-[var(--muted-foreground)] underline underline-offset-4"
          >
            {t('Leave without saving')}
          </button>
        </div>
      </Modal>
    </div>
  )
}
