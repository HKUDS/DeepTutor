'use client'

import { useState } from 'react'
import { Loader2, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Dialog } from '@/shared/ui/Dialog'
import { usePageCustomization } from '@/context/PageCustomizationContext'
import {
  DEFAULT_PAGE_CUSTOMIZATION,
  STARTER_GROUPS,
  starterPrompts,
  toggleHidden,
  type PageCustomization,
  type StarterGroup,
  type ComposerControls,
} from '@/lib/page-customization'
import type { CapabilityDef } from '@/features/capabilities/presentation'
import { useCapabilityLabel } from '@/features/ui-layout/tokens'
import { LEARNING_SURFACES } from '@/components/learning/surfaces'

const inputClass =
  'w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition-shadow focus:border-ring focus:ring-2 focus:ring-ring/15'
const actionClass =
  'inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50'

export function ChoiceRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string
  description?: string
  checked: boolean
  onChange: () => void
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={onChange}
      className="flex w-full cursor-pointer items-center gap-4 rounded-xl border border-border p-3.5 text-left transition-colors hover:bg-muted/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
    >
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium">{label}</span>
        {description && (
          <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
            {description}
          </span>
        )}
      </span>
      <span
        aria-hidden
        className={`flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition-colors ${checked ? 'bg-primary' : 'bg-muted-foreground/25'}`}
      >
        <span
          className={`h-4 w-4 rounded-full bg-background shadow-sm transition-transform motion-reduce:transition-none ${checked ? 'translate-x-4' : ''}`}
        />
      </span>
    </button>
  )
}

export default function PageCustomizeDialog({
  page,
  initial,
  capabilities,
  learningKinds,
  onClose,
}: {
  page: 'chat' | 'learning'
  initial: PageCustomization
  capabilities: CapabilityDef[]
  learningKinds?: string[]
  onClose: () => void
}) {
  const { t } = useTranslation()
  const capabilityLabel = useCapabilityLabel()
  const { save, loading, error: loadError, reload } = usePageCustomization()
  const [draft, setDraft] = useState(() => structuredClone(initial))
  const [tab, setTab] = useState<'modes' | 'controls' | 'starters'>('modes')
  const [group, setGroup] = useState<StarterGroup>('explain')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(false)
  const prompts = starterPrompts(draft.chat, group, t)
  const invalid = Object.values(draft.chat.starters).some(rows =>
    rows?.some(row => !row.label.trim() || !row.prompt.trim())
  )
  const updatePrompts = (rows: typeof prompts) =>
    setDraft(previous => ({
      ...previous,
      chat: { ...previous.chat, starters: { ...previous.chat.starters, [group]: rows } },
    }))
  async function commit() {
    setSaving(true)
    setError(false)
    try {
      await save(page, draft[page])
      onClose()
    } catch {
      setError(true)
      setSaving(false)
    }
  }
  return (
    <Dialog
      open
      title={t('customize.title')}
      description={t('customize.description')}
      onClose={onClose}
      closeLabel={t('Close')}
      size="lg"
      busy={saving}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            disabled={saving}
            className={`${actionClass} text-muted-foreground hover:bg-muted`}
            onClick={() =>
              setDraft(previous => ({
                ...previous,
                [page]: structuredClone(DEFAULT_PAGE_CUSTOMIZATION[page]),
              }))
            }
          >
            <RotateCcw size={14} />
            {t('customize.reset')}
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={saving}
              className={`${actionClass} hover:bg-muted`}
              onClick={onClose}
            >
              {t('Cancel')}
            </button>
            <button
              type="button"
              disabled={saving || loading || loadError || invalid}
              onClick={() => void commit()}
              className={`${actionClass} bg-primary text-primary-foreground hover:opacity-90`}
            >
              {saving && <Loader2 size={14} className="animate-spin" />}
              {t(saving ? 'Saving...' : 'Save')}
            </button>
          </div>
        </div>
      }
    >
      {(error || loadError) && (
        <div
          role="alert"
          className="mb-4 rounded-lg bg-destructive/10 p-3 text-sm text-destructive"
        >
          {t('customize.saveError')}
          {loadError && (
            <button type="button" className="ml-2 underline" onClick={reload}>
              {t('Retry')}
            </button>
          )}
        </div>
      )}
      {loading ? (
        <div role="status" className="flex justify-center p-12">
          <Loader2 className="animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          {page === 'chat' ? (
            <>
              <div
                className="mb-5 flex gap-1 rounded-xl bg-muted/60 p-1"
                role="group"
                aria-label={t('customize.sections')}
              >
                {(['modes', 'controls', 'starters'] as const).map(item => (
                  <button
                    key={item}
                    type="button"
                    aria-pressed={tab === item}
                    onClick={() => setTab(item)}
                    className={`flex-1 rounded-lg px-3 py-2 text-sm transition-colors ${tab === item ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
                  >
                    {t(`customize.${item}`)}
                  </button>
                ))}
              </div>
              {tab === 'modes' && (
                <div className="space-y-2">
                  <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
                    {t('customize.modesHint')}
                  </p>
                  {capabilities
                    .filter(cap => cap.value && !cap.legacy)
                    .map(cap => (
                      <ChoiceRow
                        key={cap.value}
                        label={capabilityLabel(cap)}
                        description={t(cap.description)}
                        checked={!draft.chat.hidden_modes.includes(cap.value)}
                        onChange={() =>
                          setDraft(previous => ({
                            ...previous,
                            chat: {
                              ...previous.chat,
                              hidden_modes: toggleHidden(previous.chat.hidden_modes, cap.value),
                            },
                          }))
                        }
                      />
                    ))}
                </div>
              )}
              {tab === 'controls' && (
                <div className="space-y-2">
                  {(
                    [
                      'skills',
                      'mcp',
                      'partners',
                      'preferences',
                      'voice',
                    ] as (keyof ComposerControls)[]
                  ).map(key => (
                    <ChoiceRow
                      key={key}
                      label={t(`customize.control.${key}`)}
                      checked={draft.chat.controls[key]}
                      onChange={() =>
                        setDraft(previous => ({
                          ...previous,
                          chat: {
                            ...previous.chat,
                            controls: {
                              ...previous.chat.controls,
                              [key]: !previous.chat.controls[key],
                            },
                          },
                        }))
                      }
                    />
                  ))}
                </div>
              )}
              {tab === 'starters' && (
                <>
                  <div
                    className="mb-4 flex flex-wrap gap-2"
                    role="group"
                    aria-label={t('customize.starters')}
                  >
                    {STARTER_GROUPS.map(key => (
                      <button
                        type="button"
                        key={key}
                        aria-pressed={group === key}
                        onClick={() => setGroup(key)}
                        className={`rounded-full px-3 py-1.5 text-xs transition-colors ${group === key ? 'bg-primary text-primary-foreground' : 'bg-muted/60 text-muted-foreground hover:bg-muted'}`}
                      >
                        {t(`starters.${key}`)}
                      </button>
                    ))}
                  </div>
                  <div className="space-y-3">
                    {prompts.map((row, index) => (
                      <div
                        key={`${group}-${index}`}
                        className="rounded-xl border border-border bg-muted/15 p-3"
                      >
                        <div className="mb-2 flex items-start gap-2">
                          <label className="min-w-0 flex-1">
                            <span className="mb-1.5 block text-xs text-muted-foreground">
                              {t('customize.promptLabel')}
                            </span>
                            <input
                              aria-label={`${t('customize.promptLabel')} ${index + 1}`}
                              value={row.label}
                              maxLength={160}
                              className={inputClass}
                              onChange={event =>
                                updatePrompts(
                                  prompts.map((item, i) =>
                                    i === index ? { ...item, label: event.target.value } : item
                                  )
                                )
                              }
                            />
                          </label>
                          <button
                            type="button"
                            aria-label={`${t('customize.removePrompt')} ${index + 1}`}
                            onClick={() => updatePrompts(prompts.filter((_, i) => i !== index))}
                            className="mt-6 rounded-lg p-2 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                        <label>
                          <span className="mb-1.5 block text-xs text-muted-foreground">
                            {t('customize.promptText')}
                          </span>
                          <textarea
                            aria-label={`${t('customize.promptText')} ${index + 1}`}
                            value={row.prompt}
                            maxLength={4000}
                            rows={3}
                            className={`${inputClass} resize-y`}
                            onChange={event =>
                              updatePrompts(
                                prompts.map((item, i) =>
                                  i === index ? { ...item, prompt: event.target.value } : item
                                )
                              )
                            }
                          />
                        </label>
                      </div>
                    ))}
                    {!prompts.length && (
                      <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                        {t('customize.emptyPrompts')}
                      </p>
                    )}
                  </div>
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                    <button
                      type="button"
                      disabled={prompts.length >= 20}
                      onClick={() => updatePrompts([...prompts, { label: '', prompt: '' }])}
                      className={`${actionClass} border border-border hover:bg-muted`}
                    >
                      <Plus size={14} />
                      {t('customize.addPrompt')}
                    </button>
                    <button
                      type="button"
                      className={`${actionClass} text-muted-foreground hover:bg-muted`}
                      onClick={() =>
                        setDraft(previous => {
                          const starters = { ...previous.chat.starters }
                          delete starters[group]
                          return { ...previous, chat: { ...previous.chat, starters } }
                        })
                      }
                    >
                      {t('customize.resetGroup')}
                    </button>
                  </div>
                  {invalid && (
                    <p role="status" className="mt-2 text-xs text-muted-foreground">
                      {t('customize.requiredPrompts')}
                    </p>
                  )}
                </>
              )}
            </>
          ) : (
            <div className="space-y-2">
              <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
                {t('customize.learningHint')}
              </p>
              {LEARNING_SURFACES.filter(
                surface => !learningKinds || learningKinds.includes(surface.kind)
              ).map(surface => (
                <ChoiceRow
                  key={surface.kind}
                  label={t(surface.title)}
                  description={t(surface.description)}
                  checked={!draft.learning.hidden_features.includes(surface.kind)}
                  onChange={() =>
                    setDraft(previous => ({
                      ...previous,
                      learning: {
                        hidden_features: toggleHidden(
                          previous.learning.hidden_features,
                          surface.kind
                        ),
                      },
                    }))
                  }
                />
              ))}
            </div>
          )}
        </>
      )}
    </Dialog>
  )
}
