'use client'

import { useState } from 'react'
import { createPortal } from 'react-dom'
import dynamic from 'next/dynamic'
import { SlidersHorizontal } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Tooltip from '@/shared/ui/Tooltip'
import type { CapabilityDef } from '@/features/capabilities/presentation'
import { usePageCustomization } from '@/context/PageCustomizationContext'

const PageCustomizeDialog = dynamic(() => import('./PageCustomizeDialog'))

export function PageCustomizeButton({
  page,
  capabilities = [],
  learningKinds,
  compact = false,
}: {
  page: 'chat' | 'learning'
  capabilities?: CapabilityDef[]
  learningKinds?: string[]
  compact?: boolean
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const { value, loading, error, reload } = usePageCustomization()
  return (
    <>
      <Tooltip label={t(error ? 'customize.loadError' : 'customize.title')}>
        <button
          type="button"
          aria-label={t(error ? 'customize.loadError' : 'customize.title')}
          aria-haspopup="dialog"
          disabled={loading}
          onClick={() => (error ? reload() : setOpen(true))}
          className={`inline-flex h-8 items-center justify-center gap-2 rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring ${compact ? 'w-8' : 'px-3 text-xs'}`}
        >
          <SlidersHorizontal size={15} strokeWidth={1.7} />
          {!compact && <span>{t('customize.title')}</span>}
        </button>
      </Tooltip>
      {open &&
        createPortal(
          <PageCustomizeDialog
            page={page}
            initial={value}
            capabilities={capabilities}
            learningKinds={learningKinds}
            onClose={() => setOpen(false)}
          />,
          document.body
        )}
    </>
  )
}
