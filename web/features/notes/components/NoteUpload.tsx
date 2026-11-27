'use client'

import { createReactBlockSpec } from '@blocknote/react'
import { FileUp, LoaderCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'

// Only live requests count as uploading. A saved placeholder reopened after a
// tab closes offers retry instead of displaying an endless spinner.
export const activeNoteUploads = new Set<string>()
export const noteUpload = createReactBlockSpec(
  {
    type: 'noteUpload',
    content: 'none',
    propSchema: { name: { default: '' }, error: { default: '' } },
  },
  {
    render: function UploadBlock({ block }) {
      const { t } = useTranslation()
      const pending = activeNoteUploads.has(block.id)
      return (
        <div className="dt-note-upload" contentEditable={false} aria-busy={pending}>
          {pending ? <LoaderCircle size={18} className="animate-spin" /> : <FileUp size={18} />}
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm">{block.props.name}</div>
            <p
              className="text-xs text-[var(--muted-foreground)]"
              role={block.props.error ? 'alert' : 'status'}
            >
              {pending
                ? t('Uploading…')
                : block.props.error || t('Choose the file again to finish uploading.')}
            </p>
          </div>
          {!pending && (
            <button
              className="dt-note-action"
              onClick={e =>
                e.currentTarget.dispatchEvent(
                  new CustomEvent('note-upload-retry', {
                    bubbles: true,
                    detail: { blockId: block.id },
                  })
                )
              }
            >
              {t('Choose file')}
            </button>
          )}
        </div>
      )
    },
  }
)
