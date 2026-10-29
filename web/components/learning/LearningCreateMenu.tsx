'use client'
import Link from 'next/link'
import { Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Tooltip from '@/shared/ui/Tooltip'
import { pageActionClass } from '@/components/layout/FeaturePage'
import { useSidebarDrawer } from '@/components/layout/AppShell'
import { scopedUrl, activeWorkspaceId } from '@/lib/workspace-scope'

/** All creation entry points share a bookmarkable page instead of a transient menu. */
export function LearningCreateMenu({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation()
  const drawer = useSidebarDrawer()
  return (
    <Tooltip label={t('navigation.createLearning')}>
      <Link
        href={scopedUrl('/learning/new', activeWorkspaceId())}
        aria-label={t('navigation.createLearning')}
        onClick={() => drawer?.close()}
        className={compact ? 'dt-nav-icon' : pageActionClass()}
      >
        <Plus size={compact ? 17 : 15} />
        {!compact && t('navigation.createLearning')}
      </Link>
    </Tooltip>
  )
}
