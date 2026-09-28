'use client'

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Link from 'next/link'
import { RefreshCw } from 'lucide-react'
import {
  getSystemWorkspaceSnapshot,
  type SystemWorkspaceSnapshot as Snapshot,
} from '@/lib/workspaces-api'

export function SystemWorkspaceSnapshot() {
  const { t, i18n } = useTranslation()
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function refresh() {
    setBusy(true)
    setError('')
    try {
      setSnapshot(await getSystemWorkspaceSnapshot())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="mt-4 border-t border-[var(--border)] pt-4">
      <div className="flex flex-wrap items-center gap-4 text-xs">
        <button
          type="button"
          disabled={busy}
          onClick={() => void refresh()}
          className="inline-flex items-center gap-1.5 hover:underline disabled:opacity-50"
        >
          <RefreshCw size={13} className={busy ? 'animate-spin' : ''} />
          {t('View / refresh configuration snapshot')}
        </button>
        <Link href="/space/skills" className="hover:underline">
          {t('Skills')}
        </Link>
        <Link href="/space/mcp" className="hover:underline">
          {t('MCP')}
        </Link>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-xs text-[var(--destructive)]">
          {error}
        </p>
      )}
      {snapshot && (
        <div className="mt-4 space-y-3 text-xs">
          <p className="text-[var(--muted-foreground)]">
            {t('Snapshot updated {{time}}', { time: new Date(snapshot.generated_at).toLocaleString(i18n.language) })}
          </p>
          {Object.entries(snapshot.models).map(([service, settings]) => (
            <div key={service} className="rounded-lg bg-[color-mix(in_srgb,var(--muted)_40%,transparent)] p-3">
              <p className="mb-2 font-medium uppercase">{service}</p>
              {settings.profiles.flatMap(profile =>
                profile.models.map(model => (
                  <div
                    key={`${profile.id}:${model.id}`}
                    className="flex flex-wrap justify-between gap-x-3 gap-y-1 py-1"
                  >
                    <span className="break-all">
                      {model.name || model.model}
                      {model.id === settings.active_model_id &&
                      profile.id === settings.active_profile_id
                        ? ` · ${t('Active')}`
                        : ''}
                    </span>
                    <span className="text-[var(--muted-foreground)]">
                      {profile.name || profile.binding}
                    </span>
                  </div>
                ))
              )}
              {settings.profiles.every(profile => !profile.models.length) && (
                <span className="text-[var(--muted-foreground)]">
                  {t('No models configured')}
                </span>
              )}
            </div>
          ))}
          {snapshot.mcp.length > 0 && (
            <div className="rounded-lg bg-[color-mix(in_srgb,var(--muted)_40%,transparent)] p-3">
              <p className="mb-2 font-medium">{t('MCP')}</p>
              {snapshot.mcp.map((server, index) => (
                <p key={`${server.name}:${index}`} className="py-1">
                  {server.name} · {server.transport} ·{' '}
                  {server.enabled ? t('Enabled') : t('Disabled')}
                </p>
              ))}
            </div>
          )}
          {!Object.keys(snapshot.models).length && !snapshot.mcp.length && (
            <p>
              {t('No models or MCP servers configured yet.')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
