'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Tooltip from '@/shared/ui/Tooltip'
import { Dialog } from '@/shared/ui/Dialog'
import { LEARNING_SURFACES } from './surfaces'
import { useAuthStatus } from '@/hooks/useAuthStatus'
import { navigateTask } from '@/lib/workspace-scope'
import { pageActionClass } from '@/components/layout/FeaturePage'
import { useSidebarDrawer } from '@/components/layout/AppShell'

export function LearningCreateMenu({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation()
  const router = useRouter()
  const drawer = useSidebarDrawer()
  const [open, setOpen] = useState(false)
  const { learningPolicy } = useAuthStatus()
  const surfaces = LEARNING_SURFACES.filter(
    item =>
      !learningPolicy ||
      learningPolicy.allowedSurfaces.includes(
        item.kind === 'mastery' || item.kind === 'practice' ? 'chat' : item.kind
      )
  )
  return (
    <>
      <Tooltip label={t('navigation.createLearning')} suppressed={open}>
        <button
          type="button"
          aria-label={t('navigation.createLearning')}
          onClick={() => setOpen(true)}
          className={compact ? 'dt-nav-icon' : pageActionClass()}
        >
          <Plus size={compact ? 17 : 15} />
          {!compact && t('navigation.createLearning')}
        </button>
      </Tooltip>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={t('navigation.createLearning')}
        description={t('navigation.createLearningDescription')}
        closeLabel={t('Close')}
      >
        <div className="grid grid-cols-2 gap-3">
          {surfaces.map(item => (
            <button
              key={item.kind}
              type="button"
              className="rounded-xl border border-border p-4 text-left transition-colors hover:bg-muted/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
              onClick={() => {
                setOpen(false)
                drawer?.close()
                navigateTask(`${item.href}?create=1`, router.push)
              }}
            >
              <item.icon size={22} strokeWidth={1.6} className="mb-3 text-muted-foreground" />
              <span className="block text-sm font-medium">{t(item.title)}</span>
              <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
                {t(item.description)}
              </span>
            </button>
          ))}
        </div>
      </Dialog>
    </>
  )
}
