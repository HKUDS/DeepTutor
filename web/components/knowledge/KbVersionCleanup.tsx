'use client'

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from '@/components/common/Modal'
import {
  cleanIndexVersions,
  previewIndexCleanup,
  type IndexCleanupPreview,
} from '@/features/knowledge/api/client'

export default function KbVersionCleanup({
  kbRef,
  disabled,
  onCleaned,
}: {
  kbRef: string
  disabled: boolean
  onCleaned: (versions: string[]) => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState<IndexCleanupPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  async function showPreview() {
    setOpen(true)
    setBusy(true)
    setError(null)
    setPreview(null)
    setDone(false)
    try {
      setPreview(await previewIndexCleanup(kbRef))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function clean() {
    if (!preview) return
    setBusy(true)
    setError(null)
    try {
      const result = await cleanIndexVersions(kbRef, preview.fingerprint)
      onCleaned(result.versions)
      setDone(true)
      setPreview(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setPreview(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button
        type="button"
        disabled={disabled || busy}
        onClick={() => void showPreview()}
        className="rounded-md border border-[var(--border)] px-3 py-1.5 text-xs disabled:opacity-50"
      >
        {t('Clean up old index versions')}
      </button>
      <Modal
        isOpen={open}
        onClose={() => {
          if (!busy) setOpen(false)
        }}
        title={t('Clean up old index versions')}
        width="sm"
      >
        <div className="space-y-4 p-5">
          <p className="text-sm">
            {t(
              'Keep the two newest published indexes for each embedding configuration. Original documents, unfinished indexes and versions referenced by saved learning history are preserved.'
            )}
          </p>
          {busy && <p role="status">{t('Working…')}</p>}
          {error && (
            <p role="alert" className="text-sm text-red-600">
              {error}
            </p>
          )}
          {done && <p role="status">{t('Old index versions cleaned up.')}</p>}
          {preview && (
            <p>
              {preview.versions.length > 0
                ? t('Delete {{count}} old index versions and free {{size}} MB?', {
                    count: preview.versions.length,
                    size: (preview.bytes / 1024 / 1024).toFixed(1),
                  })
                : t('No old index versions can be safely removed.')}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" disabled={busy} onClick={() => setOpen(false)}>
              {t('Close')}
            </button>
            {error && (
              <button type="button" disabled={busy || disabled} onClick={() => void showPreview()}>
                {t('Preview again')}
              </button>
            )}
            {preview && preview.versions.length > 0 && (
              <button
                type="button"
                disabled={busy || disabled}
                onClick={() => void clean()}
                className="rounded-md bg-red-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
              >
                {t('Delete old indexes')}
              </button>
            )}
          </div>
        </div>
      </Modal>
    </>
  )
}
