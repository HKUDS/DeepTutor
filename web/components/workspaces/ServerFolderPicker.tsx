'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowUp, ChevronRight, Folder } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Dialog } from '@/shared/ui/Dialog'
import {
  browseServerFolders,
  type ServerFolder,
  type ServerFolderListing,
} from '@/lib/workspaces-api'

/** Browse the backend filesystem without requiring a manually entered path. */
export function ServerFolderPicker({
  onClose,
  onSelect,
}: {
  onClose: () => void
  onSelect: (folder: ServerFolder) => void | Promise<void>
}) {
  const { t } = useTranslation()
  const [path, setPath] = useState('')
  const [listing, setListing] = useState<ServerFolderListing | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let active = true
    browseServerFolders(path)
      .then(data => {
        if (active) {
          setListing(data)
          setLoading(false)
        }
      })
      .catch(err => {
        if (active) {
          setError(String(err.message))
          setLoading(false)
        }
      })
    return () => {
      active = false
    }
  }, [path, attempt])

  const navigate = (next: string) => {
    if (next === path) return
    setLoading(true)
    setError('')
    setFilter('')
    setPath(next)
  }
  const choose = async () => {
    if (!listing || loading || saving) return
    setSaving(true)
    setError('')
    try {
      await onSelect({ name: listing.name, path: listing.path })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const currentRoot = listing?.roots
    .filter(root => {
      const current = listing.path.replaceAll('\\', '/')
      const prefix = root.path.replaceAll('\\', '/').replace(/\/$/, '')
      return current === prefix || current.startsWith(prefix + '/')
    })
    .sort((a, b) => b.path.length - a.path.length)[0]

  return createPortal(
    <Dialog
      open
      title={t('Choose a server folder')}
      onClose={onClose}
      busy={saving}
      closeLabel={t('Close')}
      size="lg"
      description={t('Browse folders on the server and choose a project workspace.')}
      footer={
        <>
          <button
            type="button"
            disabled={saving}
            onClick={onClose}
            className="rounded-lg px-3 py-2 text-sm hover:bg-[var(--muted)]"
          >
            {t('Cancel')}
          </button>
          <button
            type="button"
            disabled={loading || saving || !listing || !!error}
            onClick={() => void choose()}
            className="rounded-lg bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)] disabled:opacity-50"
          >
            {t('Select this folder')}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        {listing && (
          <>
            <div className="flex items-center gap-2">
              <button
                type="button"
                aria-label={t('Parent folder')}
                disabled={!listing.parent || loading || saving}
                onClick={() => listing.parent && navigate(listing.parent)}
                className="rounded-lg border border-[var(--border)] p-2 disabled:opacity-40"
              >
                <ArrowUp size={16} />
              </button>
              <p
                aria-label={t('Current folder')}
                className="min-w-0 flex-1 select-all break-all font-mono text-xs"
              >
                {listing.path}
              </p>
            </div>
            {listing.roots.length > 1 && (
              <select
                aria-label={t('Browse root')}
                disabled={saving || loading}
                value={currentRoot?.path ?? ''}
                onChange={event => navigate(event.target.value)}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-2 text-sm"
              >
                {listing.roots.map(root => (
                  <option key={root.path} value={root.path}>
                    {root.path}
                  </option>
                ))}
              </select>
            )}
          </>
        )}
        <input
          aria-label={t('Filter folders')}
          placeholder={t('Filter folders')}
          value={filter}
          onChange={event => setFilter(event.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
        />
        {error && (
          <div className="flex items-center gap-3">
            <p role="alert" className="text-sm text-[var(--destructive)]">
              {error}
            </p>
            <button
              type="button"
              onClick={() => {
                setLoading(true)
                setError('')
                setAttempt(value => value + 1)
              }}
              className="text-sm underline"
            >
              {t('Retry')}
            </button>
          </div>
        )}
        <div
          aria-busy={loading}
          className="h-64 overflow-y-auto rounded-lg border border-[var(--border)]"
        >
          {loading ? (
            <p role="status" className="p-4 text-sm text-[var(--muted-foreground)]">
              {t('Loading folders…')}
            </p>
          ) : (
            <>
              {listing?.folders
                .filter(folder =>
                  folder.name.toLocaleLowerCase().includes(filter.toLocaleLowerCase())
                )
                .map(folder => (
                  <button
                    type="button"
                    key={folder.path}
                    disabled={saving}
                    onClick={() => navigate(folder.path)}
                    className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-[var(--muted)]"
                  >
                    <Folder size={17} className="shrink-0 text-[var(--muted-foreground)]" />
                    <span className="min-w-0 flex-1 break-words">{folder.name}</span>
                    <ChevronRight size={15} className="shrink-0" />
                  </button>
                ))}
              {!listing?.folders.some(folder =>
                folder.name.toLocaleLowerCase().includes(filter.toLocaleLowerCase())
              ) &&
                !error && (
                  <p className="p-4 text-sm text-[var(--muted-foreground)]">{t('No subfolders')}</p>
                )}
            </>
          )}
        </div>
        {listing?.truncated && (
          <p className="text-xs text-[var(--muted-foreground)]">
            {t('Showing the first 500 folders. Open a subfolder to narrow the list.')}
          </p>
        )}
      </div>
    </Dialog>,
    document.body
  )
}
