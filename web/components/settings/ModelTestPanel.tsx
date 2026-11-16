'use client'

import { CheckCircle2, CircleAlert, FlaskConical, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  useSettings,
  type CatalogModel,
  type CatalogProfile,
  type ServiceName,
} from '@/features/settings/store/SettingsStore'
import { modelTestFingerprint, modelTestKey } from '@/lib/model-settings'
import {
  reasoningEffortOptionsFromSupportedLevels,
  VALID_REASONING_EFFORTS,
} from '@/lib/reasoning-effort'
import { formatContextWindowSource, subPanelClass } from './shared'

/** Tests the model on screen, never the runtime default. Results survive
 * navigation in Settings and are invalidated when request inputs change. */
export function ModelTestPanel({
  service,
  profile,
  model,
}: {
  service: ServiceName
  profile: CatalogProfile
  model?: CatalogModel | null
}) {
  const { t } = useTranslation()
  const { draft, modelTests, testRunning, runDetailedTest, mutateCatalog } = useSettings()
  const result = modelTests[modelTestKey(service, profile.id, model?.id)]
  const current =
    result?.fingerprint === modelTestFingerprint(draft, service, profile.id, model?.id)
  const running = current && result?.state === 'running'
  const usable = service === 'search' || Boolean(model?.model.trim())
  const context = current ? result?.context : undefined
  const dimension = current ? result?.dimension : undefined
  const reasoning = current ? result?.reasoning : undefined
  const levels = reasoning?.levels
  const selectable = reasoning?.selectableLevels === undefined ? levels : reasoning.selectableLevels
  const limited =
    Array.isArray(levels) &&
    Array.isArray(selectable) &&
    levels.some(level => !selectable.includes(level))
  const reasoningApplied =
    Array.isArray(selectable) &&
    selectable.length === model?.enabled_reasoning_efforts?.length &&
    selectable.every(level => model?.enabled_reasoning_efforts?.includes(level))
  const adoptReasoning = () =>
    mutateCatalog(next => {
      if (
        !result ||
        result.state === 'running' ||
        !Array.isArray(selectable) ||
        (selectable.length === 0 && Boolean(levels?.length)) ||
        result.fingerprint !== modelTestFingerprint(next, service, profile.id, model?.id)
      )
        return
      const target = next.services[service].profiles
        .find(item => item.id === profile.id)
        ?.models.find(item => item.id === model?.id)
      if (
        !target ||
        profile.read_only ||
        target.managed_by ||
        target.capabilities?.reasoning === false
      )
        return
      target.enabled_reasoning_efforts = selectable.filter(level =>
        VALID_REASONING_EFFORTS.has(level)
      )
    })
  const adopt = () =>
    mutateCatalog(next => {
      // A late response or a deleted model must never write into a different selection.
      if (
        !result ||
        result.fingerprint !== modelTestFingerprint(next, service, profile.id, model?.id)
      )
        return
      const target = next.services[service].profiles
        .find(item => item.id === profile.id)
        ?.models.find(item => item.id === model?.id)
      if (!target) return
      if (context) {
        target.context_window = String(context.value)
        target.context_window_source = context.source
        target.context_window_detected_at = context.detectedAt
      }
      if (dimension) {
        target.dimension = String(dimension)
        target.supported_dimensions = (result.supportedDimensions ?? []).join(',')
      }
    })
  const adopted = context
    ? Number(model?.context_window) === context.value
    : dimension
      ? Number(model?.dimension) === dimension
      : false

  return (
    <section aria-label={t('Model connection test')} className={`space-y-3 p-4 ${subPanelClass}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {service === 'search' ? t('Test search') : t('Test this model')}
          </p>
          <p className="mt-1 break-all text-xs text-[var(--muted-foreground)]">
            {model?.model || profile.name}
          </p>
        </div>
        <button
          type="button"
          disabled={!usable || testRunning !== null}
          onClick={() =>
            void runDetailedTest(service, {
              profileId: profile.id,
              modelId: model?.id,
            })
          }
          className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 text-xs font-medium hover:bg-[var(--accent)] disabled:opacity-40"
        >
          {running ? <Loader2 size={15} className="animate-spin" /> : <FlaskConical size={15} />}
          {running ? t('Testing model…') : current ? t('Test again') : t('Test model')}
        </button>
      </div>
      <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
        {service === 'llm' || service === 'task'
          ? t(
              'Sends a short request and detects the context window using these settings. Your active model stays unchanged.'
            )
          : service === 'embedding'
            ? t(
                'Tests embedding access and detects dimensions. Existing dimensions are kept until you choose to update them.'
              )
            : t(
                'Sends a sample request using these settings. Your active configuration stays unchanged.'
              )}
      </p>
      <div role="status" aria-live="polite">
        {result && !current && (
          <p className="text-xs text-amber-700 dark:text-amber-400">
            {t('Settings changed since the last test. Test again to verify them.')}
          </p>
        )}
        {current && result && (
          <div className="space-y-2">
            <p
              className={`flex items-start gap-2 text-sm ${result.state === 'success' ? 'text-emerald-700 dark:text-emerald-400' : result.state === 'failed' ? 'text-red-600 dark:text-red-400' : 'text-[var(--muted-foreground)]'}`}
            >
              {result.state === 'success' ? (
                <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
              ) : result.state === 'failed' ? (
                <CircleAlert size={16} className="mt-0.5 shrink-0" />
              ) : (
                <Loader2 size={16} className="mt-0.5 shrink-0 animate-spin" />
              )}
              <span className="break-words">
                {result.state === 'success' ? t('Model responded successfully') : result.message}
              </span>
            </p>
            {result.response && (
              <p className="break-words text-xs text-[var(--muted-foreground)]">
                {result.response}
              </p>
            )}
            {(context || dimension) && (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-[var(--background)] p-3 text-xs">
                <div>
                  <p className="font-medium">
                    {context
                      ? t(
                          context.source === 'default'
                            ? 'Unknown context capacity · conservative budget: {{count}} tokens'
                            : 'Detected context: {{count}} tokens',
                          {
                            count: context.value,
                          }
                        )
                      : t('Detected dimensions: {{count}}', {
                          count: dimension,
                        })}
                  </p>
                  {context && (
                    <p className="mt-1 text-[var(--muted-foreground)]">
                      {formatContextWindowSource(context.source, t)}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={adopt}
                  disabled={
                    context?.source === 'default' ||
                    adopted ||
                    result.state !== 'success' ||
                    Boolean(profile.read_only || model?.managed_by)
                  }
                  className="rounded-md border border-[var(--border)] px-2.5 py-1.5 disabled:opacity-50"
                >
                  {context?.source === 'default'
                    ? t('Set context capacity manually')
                    : adopted
                      ? t('Already applied')
                      : t('Use detected value')}
                </button>
              </div>
            )}
            {reasoning && (
              <div className="space-y-2 rounded-lg bg-[var(--background)] p-3 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="font-medium">{t('Supported reasoning levels')}</p>
                  {Array.isArray(levels) && (
                    <button
                      type="button"
                      onClick={adoptReasoning}
                      disabled={
                        !Array.isArray(selectable) ||
                        (selectable.length === 0 && levels.length > 0) ||
                        reasoningApplied ||
                        result.state === 'running' ||
                        Boolean(
                          profile.read_only ||
                          model?.managed_by ||
                          model?.capabilities?.reasoning === false
                        )
                      }
                      className="min-h-8 rounded-md border border-[var(--border)] px-2.5 py-1.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ring)] disabled:opacity-50"
                    >
                      {t(reasoningApplied ? 'Already applied' : 'Use detected levels')}
                    </button>
                  )}
                </div>
                {Array.isArray(levels) ? (
                  <>
                    <div className="flex flex-wrap gap-1.5">
                      {reasoningEffortOptionsFromSupportedLevels(levels)
                        .filter(item => item.value)
                        .map(item => (
                          <span
                            key={item.value}
                            className="rounded-md border border-[var(--border)] px-2 py-1"
                          >
                            {VALID_REASONING_EFFORTS.has(item.value) ? t(item.label) : item.value}
                          </span>
                        ))}
                    </div>
                    {!levels.length && <p>{t('No configurable reasoning levels reported.')}</p>}
                    {limited && (
                      <p className="text-[var(--muted-foreground)]">
                        {t('Selectable through this connection: {{levels}}', {
                          levels:
                            reasoningEffortOptionsFromSupportedLevels(selectable ?? [])
                              .filter(item => item.value)
                              .map(item => t(item.label))
                              .join(', ') || t('None'),
                        })}
                      </p>
                    )}
                    <p className="text-[var(--muted-foreground)]">
                      {t(
                        reasoning.source === 'managed_catalog'
                          ? 'Managed model catalog'
                          : 'Provider model metadata'
                      )}
                    </p>
                    {model?.capabilities?.reasoning === false && (
                      <p className="text-[var(--muted-foreground)]">
                        {t('Enable reasoning in model capabilities to use these levels.')}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-[var(--muted-foreground)]">
                    {t('Reasoning levels could not be determined. Keep your manual selection.')}
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
      {current && result?.logs && (
        <details>
          <summary className="cursor-pointer text-xs text-[var(--muted-foreground)]">
            {t('Test details')}
          </summary>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[var(--background)] p-3 font-mono text-[11px] leading-5">
            {result.logs}
          </pre>
        </details>
      )}
    </section>
  )
}
