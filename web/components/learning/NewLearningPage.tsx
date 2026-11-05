'use client'

import { useRouter } from 'next/navigation'
import { ArrowUpRight, Plus, Settings2 } from 'lucide-react'
import { m, useReducedMotion } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { useAuthStatus } from '@/hooks/useAuthStatus'
import { useModules } from '@/hooks/useModules'
import { usePageCustomization } from '@/context/PageCustomizationContext'
import { PageCustomizeButton } from '@/components/customization/PageCustomizeButton'
import { navigateTask } from '@/lib/workspace-scope'
import { LEARNING_SURFACES } from './surfaces'
import {
  LearningShell,
  LearningSkeleton,
  LearningErrorState,
  LearningEmptyState,
} from './LearningShell'

export default function NewLearningPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const reduced = useReducedMotion()
  const auth = useAuthStatus()
  const inventory = useModules()
  const preferences = usePageCustomization()
  const eligible = LEARNING_SURFACES.filter(
    item =>
      inventory.available(item.href) &&
      (!auth.learningPolicy ||
        auth.learningPolicy.allowedSurfaces.includes(
          item.kind === 'mastery' || item.kind === 'practice' ? 'chat' : item.kind
        ))
  )
  const surfaces = eligible.filter(
    item => !preferences.value.learning.hidden_features.includes(item.kind)
  )
  const learningKinds = eligible.map(item => item.kind)
  const loading = auth.loading || preferences.loading || (!inventory.modules && !inventory.error)
  return (
    <LearningShell
      title={t('navigation.createLearning')}
      subtitle={t('navigation.createLearningDescription')}
      icon={Plus}
      back={false}
      action={<PageCustomizeButton page="learning" learningKinds={learningKinds} />}
    >
      {(inventory.error || preferences.error) && (
        <LearningErrorState
          message={t('customize.loadError')}
          onRetry={() => {
            inventory.reload()
            preferences.reload()
          }}
        />
      )}
      {loading ? (
        <LearningSkeleton count={4} />
      ) : surfaces.length ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:gap-5">
          {surfaces.map((item, index) => (
            <m.div
              key={item.kind}
              initial={reduced ? false : { opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: reduced ? 0 : 0.22, delay: reduced ? 0 : index * 0.04 }}
            >
              <button
                type="button"
                onClick={() => navigateTask(`${item.href}?create=1`, router.push)}
                className="group flex h-full min-h-56 w-full flex-col rounded-2xl border border-border bg-card p-6 text-left shadow-sm transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring active:translate-y-0 motion-reduce:transform-none"
              >
                <span className="mb-6 flex w-full items-center justify-between">
                  <span
                    className={`inline-flex h-11 w-11 items-center justify-center rounded-xl ${item.accent}`}
                  >
                    <item.icon size={23} strokeWidth={1.6} />
                  </span>
                  <ArrowUpRight
                    size={18}
                    className="text-muted-foreground/50 transition-colors group-hover:text-foreground"
                  />
                </span>
                <span className="font-serif text-xl font-semibold tracking-tight">
                  {t(item.title)}
                </span>
                <span className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
                  {t(item.description)}
                </span>
              </button>
            </m.div>
          ))}
        </div>
      ) : (
        !inventory.error && (
          <LearningEmptyState
            icon={<Settings2 size={28} />}
            title={t('customize.emptyLearning')}
            description={t('customize.emptyLearningHint')}
            action={<PageCustomizeButton page="learning" learningKinds={learningKinds} />}
          />
        )
      )}
      {!loading && (
        <p className="mt-6 text-xs leading-relaxed text-muted-foreground">
          {t('customize.learningFooter')}
        </p>
      )}
    </LearningShell>
  )
}
